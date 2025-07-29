import sys
import json
import time
import random
import re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget,
                             QTableWidgetItem, QProgressBar, QFileDialog, QMessageBox,
                             QHeaderView, QTabWidget, QTextEdit, QCheckBox, QGroupBox,
                             QDialog, QFormLayout, QDialogButtonBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon


class CookieDialog(QDialog):
    """Cookie设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置B站Cookie")
        self.setWindowIcon(QIcon("bilibili.ico"))
        self.resize(500, 200)

        layout = QVBoxLayout()

        # 表单布局
        form_layout = QFormLayout()

        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText("输入您的B站Cookie（包含SESSDATA等）")
        form_layout.addRow("Cookie:", self.cookie_input)

        # 说明文本
        help_label = QLabel(
            "如何获取Cookie：\n"
            "1. 登录B站网页版\n"
            "2. 按F12打开开发者工具\n"
            "3. 转到Network(网络)选项卡\n"
            "4. 刷新页面\n"
            "5. 点击任意请求，在Headers中找到Cookie字段并复制"
        )
        help_label.setStyleSheet("color: #666666; font-size: 11px;")

        # 按钮组
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout.addLayout(form_layout)
        layout.addWidget(help_label)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def get_cookie(self):
        return self.cookie_input.text().strip()


class BiliCommentAPI:
    """B站评论API封装类"""

    def __init__(self, cookie=None):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.bilibili.com'
        }
        if cookie:
            self.headers['Cookie'] = cookie
        self.proxies = None
        self.delay = (1, 3)  # 请求延迟范围(秒)
        self.timeout = 10
        self.retry = 3

    def set_cookie(self, cookie):
        """动态设置Cookie"""
        self.headers['Cookie'] = cookie

    def set_proxy(self, proxy_str):
        """设置代理"""
        if proxy_str:
            self.proxies = {
                'http': proxy_str,
                'https': proxy_str
            }

    def get_video_info(self, bvid):
        """获取视频信息"""
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        return self._request(url)

    def get_comments_main(self, oid, page=1, mode=3):
        """获取主评论"""
        url = "https://api.bilibili.com/x/v2/reply/main"
        params = {
            'type': 1,
            'oid': oid,
            'next': page,
            'mode': mode,  # 3-热度 2-时间 1-推荐
            'ps': 20
        }
        return self._request(url, params)

    def get_comments_reply(self, oid, root_rpid, page=1):
        """获取子评论"""
        url = "https://api.bilibili.com/x/v2/reply/reply"
        params = {
            'type': 1,
            'oid': oid,
            'root': root_rpid,
            'ps': 20,
            'pn': page
        }
        return self._request(url, params)

    def _request(self, url, params=None):
        """封装请求逻辑"""
        for attempt in range(self.retry):
            try:
                time.sleep(random.uniform(*self.delay))
                resp = self.session.get(
                    url,
                    params=params,
                    headers=self.headers,
                    proxies=self.proxies,
                    timeout=self.timeout
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('code') == 0:
                        return data
                    elif data.get('code') == -412:  # 被拦截
                        time.sleep(5)
                elif resp.status_code == 412:
                    time.sleep(10)
            except Exception:
                time.sleep(2)
        return None


class CommentWorker(QThread):
    """评论爬取工作线程"""
    progress_updated = pyqtSignal(int, int, str, int)  # 当前页,总页,模式,评论数
    page_finished = pyqtSignal(dict)
    finished = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, bvid, config):
        super().__init__()
        self.bvid = bvid
        self.config = config
        self.api = BiliCommentAPI(cookie=config.get('cookie'))
        if config.get('proxy'):
            self.api.set_proxy(config['proxy'])
        self.running = True

    def run(self):
        try:
            video_info = self.api.get_video_info(self.bvid)
            if not video_info:
                self.error_occurred.emit("获取视频信息失败")
                return

            oid = video_info.get('data', {}).get('aid')
            if not oid:
                self.error_occurred.emit("无法获取视频ID")
                return

            all_comments = []
            mode = self.config.get('mode', 3)
            max_pages = self.config.get('max_pages', 10)

            for page in range(1, max_pages + 1):
                if not self.running:
                    break

                self.progress_updated.emit(page, max_pages, str(mode), len(all_comments))
                data = self.api.get_comments_main(oid, page, mode)

                if not data or not data.get('data', {}).get('replies'):
                    break

                replies = data['data']['replies']
                all_comments.extend(replies)
                self.page_finished.emit({
                    'page': page,
                    'comments': replies
                })

                # 如果需要爬取子评论
                if self.config.get('fetch_replies', False):
                    for root in replies[:5]:  # 每条主评论爬5条回复
                        if root['count'] > 0:
                            reply_data = self.api.get_comments_reply(oid, root['rpid'], 1)
                            if reply_data and reply_data.get('data', {}).get('replies'):
                                all_comments.extend(reply_data['data']['replies'])

            if self.running:
                self.finished.emit(all_comments)

        except Exception as e:
            self.error_occurred.emit(f"爬取失败: {str(e)}")

    def stop(self):
        self.running = False


class BiliCommentTool(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("B站评论爬取工具")
        self.setWindowIcon(QIcon("bilibili.ico"))
        self.resize(1000, 700)

        self.worker = None
        self.comments = []
        self.current_cookie = None
        self.setup_ui()

    def setup_ui(self):
        """初始化UI"""
        main_widget = QWidget()
        main_layout = QVBoxLayout()

        # 顶部控制区域
        control_layout = QHBoxLayout()

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("请输入B站视频URL (如: https://www.bilibili.com/video/BV1xx411c7mD)")
        self.url_input.setStyleSheet("QLineEdit { padding: 6px; }")

        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 100)
        self.page_spin.setValue(10)
        self.page_spin.setPrefix("爬取页数: ")

        from PyQt5.QtWidgets import QComboBox
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["热度排序", "时间排序", "推荐排序"])

        self.start_btn = QPushButton("开始爬取")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #00A1D6;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0088B7;
            }
            QPushButton:disabled {
                background-color: #CCCCCC;
            }
        """)
        self.start_btn.clicked.connect(self.start_scraping)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_scraping)

        # Cookie设置按钮
        self.cookie_btn = QPushButton("设置Cookie")
        self.cookie_btn.setToolTip("点击设置B站Cookie以获取更多评论")
        self.cookie_btn.clicked.connect(self.show_cookie_dialog)

        control_layout.addWidget(self.url_input, 4)
        control_layout.addWidget(self.page_spin, 1)
        control_layout.addWidget(self.mode_combo, 1)
        control_layout.addWidget(self.start_btn, 1)
        control_layout.addWidget(self.stop_btn, 1)
        control_layout.addWidget(self.cookie_btn, 1)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #00A1D6;
            }
        """)

        # 状态标签
        self.status_label = QLabel("就绪 | 请输入B站视频URL并点击开始爬取")
        self.status_label.setStyleSheet("color: #666666;")

        # 创建标签页
        tab_widget = QTabWidget()

        # 评论表格
        self.comment_table = QTableWidget()
        self.comment_table.setColumnCount(5)
        self.comment_table.setHorizontalHeaderLabels(['序号', '用户', '评论', '点赞', '时间'])
        self.comment_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.comment_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.comment_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.comment_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.comment_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.comment_table.verticalHeader().setVisible(False)
        self.comment_table.setEditTriggers(QTableWidget.NoEditTriggers)
        tab_widget.addTab(self.comment_table, "评论列表")

        # 原始数据
        self.raw_data_view = QTextEdit()
        self.raw_data_view.setReadOnly(True)
        tab_widget.addTab(self.raw_data_view, "原始数据")

        # 底部按钮
        button_layout = QHBoxLayout()

        self.save_btn = QPushButton("保存结果")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_results)

        self.clear_btn = QPushButton("清空结果")
        self.clear_btn.clicked.connect(self.clear_results)

        button_layout.addStretch(1)
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.clear_btn)

        # 组装主布局
        main_layout.addLayout(control_layout)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(tab_widget, 1)
        main_layout.addLayout(button_layout)

        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # 状态栏
        self.statusBar().showMessage("B站评论爬取工具 v1.0 | 仅供学习交流使用")

    def show_cookie_dialog(self):
        """显示Cookie设置对话框"""
        dialog = CookieDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.current_cookie = dialog.get_cookie()
            self.statusBar().showMessage("Cookie已设置", 3000)

    def start_scraping(self):
        """开始爬取"""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "输入错误", "请输入B站视频URL")
            return

        bvid = self.extract_bvid(url)
        if not bvid:
            QMessageBox.warning(self, "URL错误", "无法从URL中提取视频BV号")
            return

        # 准备配置
        config = {
            'mode': self.mode_combo.currentIndex() + 1,  # 1-3
            'max_pages': self.page_spin.value(),
            'fetch_replies': True,
            'cookie': self.current_cookie
        }

        # 清空旧数据
        self.clear_results()

        # 更新UI状态
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self.status_label.setText("正在初始化爬取任务...")
        self.progress_bar.setValue(0)

        # 创建并启动工作线程
        self.worker = CommentWorker(bvid, config)
        self.worker.progress_updated.connect(self.update_progress)
        self.worker.page_finished.connect(self.add_comments)
        self.worker.finished.connect(self.on_finished)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.start()

    def stop_scraping(self):
        """停止爬取"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.status_label.setText("爬取已停止")
            self.stop_btn.setEnabled(False)
            self.start_btn.setEnabled(True)

    def extract_bvid(self, url):
        """从URL中提取BV号"""
        patterns = [
            r'/video/(BV\w+)',
            r'/video/BV\w+',
            r'BV\w+'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1) if len(match.groups()) > 0 else match.group(0)
        return None

    def update_progress(self, current_page, total_pages, mode, comment_count):
        mode_names = {1: "推荐", 2: "时间", 3: "热度"}  # 确保有此字典定义
        self.status_label.setText(
            f"正在爬取({mode_names.get(int(mode), mode)}排序): "  
            f"第 {current_page}/{total_pages} 页 | 已获取 {comment_count} 条评论"
        )

    def add_comments(self, page_data):
        """添加评论到表格"""
        for comment in page_data['comments']:
            row = self.comment_table.rowCount()
            self.comment_table.insertRow(row)

            self.comment_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.comment_table.setItem(row, 1, QTableWidgetItem(comment['member']['uname']))

            content = comment['content']['message']
            content_item = QTableWidgetItem(content[:100] + "..." if len(content) > 100 else content)
            content_item.setToolTip(content)
            self.comment_table.setItem(row, 2, content_item)

            self.comment_table.setItem(row, 3, QTableWidgetItem(str(comment['like'])))

            time_str = datetime.fromtimestamp(comment['ctime']).strftime('%Y-%m-%d %H:%M')
            self.comment_table.setItem(row, 4, QTableWidgetItem(time_str))

        # 更新原始数据视图
        self.comments.extend(page_data['comments'])
        self.raw_data_view.setPlainText(json.dumps(self.comments, ensure_ascii=False, indent=2))

    def on_finished(self, results):
        """爬取完成处理"""
        self.progress_bar.setValue(100)
        self.status_label.setText(f"爬取完成! 共获取 {len(results)} 条评论")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(True)
        self.worker = None

    def on_error(self, error_msg):
        """错误处理"""
        QMessageBox.critical(self, "错误", error_msg)
        self.status_label.setText(f"错误: {error_msg}")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.worker = None

    def save_results(self):
        """保存结果"""
        if not self.comments:
            QMessageBox.warning(self, "无数据", "没有可保存的评论数据")
            return

        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存结果", "",
            "JSON文件 (*.json);;CSV文件 (*.csv);;文本文件 (*.txt)",
            options=options)

        if not file_path:
            return

        try:
            if file_path.endswith('.json'):
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'video_url': self.url_input.text(),
                        'scrape_time': datetime.now().isoformat(),
                        'comments': self.comments
                    }, f, ensure_ascii=False, indent=2)
            elif file_path.endswith('.csv'):
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("序号,用户名,评论内容,点赞数,时间\n")
                    for idx, comment in enumerate(self.comments, 1):
                        content = comment['content']['message'].replace('"', '""')
                        time_str = datetime.fromtimestamp(comment['ctime']).strftime('%Y-%m-%d %H:%M')
                        f.write(f'{idx},"{comment['member']['uname']}","{content}",{comment['like']},{time_str}\n')
            elif file_path.endswith('.txt'):
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(f"B站视频评论爬取结果\n")
                    f.write(f"视频URL: {self.url_input.text()}\n")
                    f.write(f"爬取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"评论数量: {len(self.comments)}\n\n")
                    for idx, comment in enumerate(self.comments, 1):
                        f.write(f"{idx}. {comment['member']['uname']}\n")
                        f.write(f"   内容: {comment['content']['message']}\n")
                        f.write(
                            f"   点赞: {comment['like']} | 时间: {datetime.fromtimestamp(comment['ctime']).strftime('%Y-%m-%d %H:%M')}\n\n")

            QMessageBox.information(self, "保存成功", f"结果已保存到:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存文件时出错:\n{str(e)}")

    def clear_results(self):
        """清空结果"""
        if self.comments and not QMessageBox.question(
                self, "确认", "确定要清空所有结果吗?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            return

        self.comment_table.setRowCount(0)
        self.raw_data_view.clear()
        self.comments = []
        self.progress_bar.setValue(0)
        self.save_btn.setEnabled(False)
        self.status_label.setText("就绪 | 结果已清空")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # 设置全局字体
    font = app.font()
    font.setFamily("Microsoft YaHei")
    font.setPointSize(10)
    app.setFont(font)

    window = BiliCommentTool()
    window.show()
    sys.exit(app.exec_())