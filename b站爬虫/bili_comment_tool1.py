import sys
import json
import time
import random
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QProgressBar, QFileDialog, QMessageBox,
    QHeaderView, QTabWidget, QTextEdit
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QColor


class BiliCommentAPI:
    """封装B站评论API请求"""

    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.bilibili.com',
            'Cookie': 'SESSDATA=f90e3649%2C1754313750%2C80128%2A22CjB4BQwYdDx0iVR0L4Cci2PuJJOBGw4wnKxXHCbeNKUn6ZrJkPLQvXzlRlvcATdJkK8SVkxmQkVYQ01VYUQ2SEtLMWpqVUtvSzM2eG1iQVNySjIzZkZObzZZS2UyVjBxOUFnLWRVS2xHQjRUZHJpSWJnUUlxVDR6cmRybXIzekhLSEdUNWVUNVFnIIEC; bili_jct=0f6c4374b73186c94bfb04e2d8d8087f'  # 替换为实际值
        }
        self.csrf_token = '0f6c4374b73186c94bfb04e2d8d8087f'  # 与Cookie中的bili_jct相同
        self.min_delay = 1.5
        self.max_delay = 3.0
        self.max_retries = 3

    def get_video_info(self, bvid):
        """获取视频基本信息"""
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        try:
            time.sleep(random.uniform(self.min_delay, self.max_delay))
            resp = self.session.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('data', {})
        except Exception as e:
            print(f"获取视频信息失败: {str(e)}")
        return None

    def get_comments_page(self, oid, next_page=0):
        """获取单页评论（新版API）"""
        url = "https://api.bilibili.com/x/v2/reply/main"
        params = {
            'type': 1,
            'oid': oid,
            'next': next_page,
            'mode': 3,
            'ps': 20,
            'csrf': self.csrf_token
        }

        for attempt in range(self.max_retries):
            try:
                time.sleep(random.uniform(self.min_delay, self.max_delay))
                resp = self.session.get(url, params=params, headers=self.headers, timeout=10)

                if resp.status_code == 412:  # 触发反爬
                    time.sleep(10)
                    continue

                data = resp.json()
                if data.get('code') == 0:
                    return data.get('data', {})
            except Exception as e:
                print(f"请求失败（尝试 {attempt + 1}/{self.max_retries}）: {str(e)}")
                time.sleep(2)
        return None


class CommentWorker(QThread):
    """多线程评论爬取工作器"""
    progress_updated = pyqtSignal(int, int, int)  # 当前页, 总页数, 评论数
    page_finished = pyqtSignal(dict)  # 单页数据
    finished = pyqtSignal(list)  # 全部完成
    error_occurred = pyqtSignal(str)  # 错误信息

    def __init__(self, bvid, max_pages=10):
        super().__init__()
        self.bvid = bvid
        self.max_pages = max_pages
        self.api = BiliCommentAPI()
        self.running = True

    def run(self):
        try:
            video_info = self.api.get_video_info(self.bvid)
            if not video_info:
                self.error_occurred.emit("获取视频信息失败")
                return

            oid = video_info.get('aid')
            if not oid:
                self.error_occurred.emit("无法获取视频ID")
                return

            results = []
            next_page = 0
            page_count = 0

            while self.running and page_count < self.max_pages:
                data = self.api.get_comments_page(oid, next_page)
                if not data or not data.get('replies'):
                    break

                replies = data.get('replies', [])
                results.extend(replies)
                page_count += 1

                self.page_finished.emit({
                    'page': page_count,
                    'replies': replies,
                    'total': len(results)
                })
                self.progress_updated.emit(page_count, self.max_pages, len(results))

                next_page = data.get('cursor', {}).get('next', 0)
                if next_page == 0:
                    break

            if self.running:
                self.finished.emit(results)
        except Exception as e:
            self.error_occurred.emit(f"爬取失败: {str(e)}")

    def stop(self):
        self.running = False


class CommentTableWidget(QTableWidget):
    """评论表格控件"""

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        self.setColumnCount(5)
        self.setHorizontalHeaderLabels(['序号', '用户', '评论', '点赞', '时间'])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.setStyleSheet("""
            QTableWidget {
                font-size: 12px;
                selection-background-color: #E1F5FE;
            }
            QHeaderView::section {
                background-color: #00A1D6;
                color: white;
                padding: 4px;
            }
        """)

    def add_comment(self, idx, comment):
        row = self.rowCount()
        self.insertRow(row)

        self.setItem(row, 0, QTableWidgetItem(str(idx)))
        self.setItem(row, 1, QTableWidgetItem(comment['member']['uname']))

        content = comment['content']['message']
        content_item = QTableWidgetItem(content[:100] + "..." if len(content) > 100 else content)
        content_item.setToolTip(content)
        self.setItem(row, 2, content_item)

        self.setItem(row, 3, QTableWidgetItem(str(comment['like'])))

        time_str = datetime.fromtimestamp(comment['ctime']).strftime('%Y-%m-%d %H:%M')
        self.setItem(row, 4, QTableWidgetItem(time_str))


class BiliCommentTool(QMainWindow):
    """主界面"""

    def __init__(self):
        super().__init__()
        self.setup_ui()
        self.comments = []
        self.worker = None

    def setup_ui(self):
        self.setWindowTitle("B站评论爬取工具")
        self.setWindowIcon(QIcon("bilibili.ico"))
        self.resize(1000, 700)

        # 主控件
        main_widget = QWidget()
        main_layout = QVBoxLayout()

        # 输入区域
        input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("输入B站视频URL（如：https://www.bilibili.com/video/BV1xx411c7mD）")
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 100)
        self.page_spin.setValue(10)
        self.page_spin.setPrefix("爬取页数：")
        self.start_btn = QPushButton("开始爬取")
        self.start_btn.clicked.connect(self.start_scraping)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_scraping)

        input_layout.addWidget(self.url_input, 4)
        input_layout.addWidget(self.page_spin, 1)
        input_layout.addWidget(self.start_btn, 1)
        input_layout.addWidget(self.stop_btn, 1)

        # 进度显示
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.status_label = QLabel("就绪 | 请输入B站视频URL")

        # 结果展示
        self.tab_widget = QTabWidget()
        self.comment_table = CommentTableWidget()
        self.raw_data_view = QTextEdit()
        self.raw_data_view.setReadOnly(True)
        self.tab_widget.addTab(self.comment_table, "评论列表")
        self.tab_widget.addTab(self.raw_data_view, "原始数据")

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

        # 组装界面
        main_layout.addLayout(input_layout)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.tab_widget, 1)
        main_layout.addLayout(button_layout)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

    def extract_bvid(self, url):
        """从URL提取BV号"""
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

    def start_scraping(self):
        """开始爬取"""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "错误", "请输入B站视频URL")
            return

        bvid = self.extract_bvid(url)
        if not bvid:
            QMessageBox.warning(self, "错误", "无法从URL中提取BV号")
            return

        self.clear_results()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self.status_label.setText("正在初始化...")
        self.progress_bar.setValue(0)

        self.worker = CommentWorker(bvid, self.page_spin.value())
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

    def update_progress(self, current, total, count):
        """更新进度"""
        self.progress_bar.setValue(int((current / total) * 100))
        self.status_label.setText(f"正在爬取：第 {current}/{total} 页 | 已获取 {count} 条评论")

    def add_comments(self, page_data):
        """添加评论到界面"""
        for comment in page_data['replies']:
            self.comment_table.add_comment(self.comment_table.rowCount() + 1, comment)
            self.comments.append(comment)
        self.raw_data_view.setPlainText(json.dumps(self.comments, ensure_ascii=False, indent=2))

    def on_finished(self, results):
        """爬取完成处理"""
        self.progress_bar.setValue(100)
        self.status_label.setText(f"爬取完成！共获取 {len(results)} 条评论")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(True)
        self.worker = None

    def on_error(self, error_msg):
        """错误处理"""
        QMessageBox.critical(self, "错误", error_msg)
        self.status_label.setText(f"错误：{error_msg}")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.worker = None

    def save_results(self):
        """保存结果"""
        if not self.comments:
            QMessageBox.warning(self, "警告", "没有可保存的数据")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存结果", "",
            "JSON文件 (*.json);;CSV文件 (*.csv);;文本文件 (*.txt)")

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
                with open(file_path, 'w', encoding='utf-8', newline='') as f:
                    f.write("序号,用户名,评论内容,点赞数,时间\n")
                    for idx, comment in enumerate(self.comments, 1):
                        content = comment['content']['message'].replace('"', '""')
                        time_str = datetime.fromtimestamp(comment['ctime']).strftime('%Y-%m-%d %H:%M')
                        f.write(f'{idx},"{comment['member']['uname']}","{content}",{comment['like']},{time_str}\n')
            elif file_path.endswith('.txt'):
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(f"B站评论爬取结果\n{'=' * 30}\n")
                    f.write(f"视频URL: {self.url_input.text()}\n")
                    f.write(f"爬取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"评论数量: {len(self.comments)}\n\n")
                    for idx, comment in enumerate(self.comments, 1):
                        f.write(f"{idx}. 用户：{comment['member']['uname']}\n")
                        f.write(f"   评论：{comment['content']['message']}\n")
                        f.write(
                            f"   点赞：{comment['like']} | 时间：{datetime.fromtimestamp(comment['ctime']).strftime('%Y-%m-%d %H:%M')}\n\n")

            QMessageBox.information(self, "成功", f"结果已保存到：\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：\n{str(e)}")

    def clear_results(self):
        """清空结果"""
        if self.comments and QMessageBox.question(
                self, "确认", "确定要清空所有结果吗？",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.No:
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
    window = BiliCommentTool()
    window.show()
    sys.exit(app.exec_())
