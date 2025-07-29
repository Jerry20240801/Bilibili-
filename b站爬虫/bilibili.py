import sys
import random
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QFileDialog, QSpinBox,
                             QTextEdit, QWidget, QMessageBox, QGroupBox, QProgressBar)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QIcon


class Worker(QObject):
    progress_updated = pyqtSignal(int)
    loading_completed = pyqtSignal(list)
    lottery_completed = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.comments = []
        self.filtered_comments = []
        self.min_words = 0
        self.num_winners = 1

    def load_comments(self, file_path):
        """严格按照B站评论格式解析文件"""
        comments = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            total_lines = len(lines)
            processed = 0
            i = 0

            while i < len(lines):
                line = lines[i].strip()

                # 更新进度 (每处理10条评论更新一次)
                if processed % 10 == 0:
                    progress = int((i / total_lines) * 100)
                    self.progress_updated.emit(progress)

                # 跳过文件头信息
                if line.startswith("B站视频评论爬取结果"):
                    while i < len(lines) and not lines[i].strip().startswith("1. "):
                        i += 1
                    continue

                # 检测评论起始行 (严格匹配"数字. 用户名"格式)
                if line and line[0].isdigit() and '. ' in line:
                    try:
                        # 1. 提取用户名
                        username = line.split('. ')[1].strip()

                        # 2. 提取评论内容 (必须包含"内容: "前缀)
                        i += 1
                        if i >= len(lines):
                            break
                        content_line = lines[i].strip()
                        if not content_line.startswith("内容: "):
                            raise ValueError(f"内容格式错误，行 {i + 1}")
                        content = content_line[3:].strip()  # 去掉"内容: "

                        # 3. 提取点赞数和时间 (必须包含指定格式)
                        i += 1
                        if i >= len(lines):
                            break
                        info_line = lines[i].strip()
                        if "点赞: " not in info_line or "|" not in info_line or "时间: " not in info_line:
                            raise ValueError(f"信息格式错误，行 {i + 1}")

                        # 分割点赞和时间部分
                        likes_part, time_part = info_line.split("|", 1)

                        # 提取点赞数
                        likes = int(likes_part.split("点赞: ")[1].strip())

                        # 提取时间
                        time = time_part.split("时间: ")[1].strip()

                        # 添加到评论列表
                        comments.append({
                            'username': username,
                            'content': content,
                            'likes': likes,
                            'time': time
                        })
                        processed += 1

                        # 跳过空行
                        i += 2  # 当前行+空行

                    except Exception as e:
                        self.progress_updated.emit(-2)  # 发送格式错误信号
                        i += 1  # 尝试恢复解析
                else:
                    i += 1

            self.comments = comments
            self.loading_completed.emit(comments)
            self.progress_updated.emit(100)

        except Exception as e:
            self.progress_updated.emit(-1)  # 发送错误信号

    def filter_comments(self):
        """过滤评论(根据最小字数)"""
        self.filtered_comments = [c for c in self.comments if len(c['content']) >= self.min_words]

    def run_lottery(self):
        """执行抽奖"""
        self.filter_comments()
        if not self.filtered_comments:
            self.lottery_completed.emit([])
            return

        num_winners = min(self.num_winners, len(self.filtered_comments))
        winners = random.sample(self.filtered_comments, num_winners)
        self.lottery_completed.emit(winners)


class CommentLotteryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("B站评论抽奖工具")
        self.setWindowIcon(QIcon("bilibili_icon.png"))  # 请准备一个图标文件或注释掉这行
        self.setGeometry(100, 100, 800, 600)

        # 初始化UI
        self.init_ui()

        # 存储评论数据
        self.comments = []
        self.filtered_comments = []

        # 多线程相关
        self.worker_thread = QThread()
        self.worker = Worker()
        self.worker.moveToThread(self.worker_thread)

        # 连接信号槽
        self.worker.progress_updated.connect(self.update_progress)
        self.worker.loading_completed.connect(self.on_loading_completed)
        self.worker.lottery_completed.connect(self.on_lottery_completed)

        self.worker_thread.start()

    def init_ui(self):
        # 主窗口布局
        main_widget = QWidget()
        main_layout = QVBoxLayout()

        # 标题
        title_label = QLabel("B站评论抽奖工具")
        title_label.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: #23ADE5; margin-bottom: 20px;")

        # 设置区域
        settings_group = QGroupBox("抽奖设置")
        settings_layout = QVBoxLayout()

        # 文件选择
        file_layout = QHBoxLayout()
        file_label = QLabel("选择评论文件:")
        file_label.setFont(QFont("Microsoft YaHei", 10))
        self.file_path_label = QLabel("未选择文件")
        self.file_path_label.setFont(QFont("Microsoft YaHei", 9))
        self.file_path_label.setStyleSheet("color: #666;")
        file_button = QPushButton("浏览...")
        file_button.setFont(QFont("Microsoft YaHei", 10))
        file_button.setStyleSheet("""
            QPushButton {
                background-color: #23ADE5; 
                color: white; 
                padding: 5px 10px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1E9BD4;
            }
        """)
        file_button.clicked.connect(self.select_file)

        file_layout.addWidget(file_label)
        file_layout.addWidget(self.file_path_label, 1)
        file_layout.addWidget(file_button)

        # 抽奖人数设置
        winner_layout = QHBoxLayout()
        winner_label = QLabel("中奖人数:")
        winner_label.setFont(QFont("Microsoft YaHei", 10))
        self.winner_spin = QSpinBox()
        self.winner_spin.setRange(1, 100)
        self.winner_spin.setValue(1)
        self.winner_spin.setFont(QFont("Microsoft YaHei", 10))

        winner_layout.addWidget(winner_label)
        winner_layout.addWidget(self.winner_spin)
        winner_layout.addStretch()

        # 最小字数设置
        min_words_layout = QHBoxLayout()
        min_words_label = QLabel("最小评论字数:")
        min_words_label.setFont(QFont("Microsoft YaHei", 10))
        self.min_words_spin = QSpinBox()
        self.min_words_spin.setRange(0, 1000)
        self.min_words_spin.setValue(0)
        self.min_words_spin.setFont(QFont("Microsoft YaHei", 10))

        min_words_layout.addWidget(min_words_label)
        min_words_layout.addWidget(self.min_words_spin)
        min_words_layout.addStretch()

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("等待操作...")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #D6E9F5;
                border-radius: 3px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #23ADE5;
                width: 10px;
            }
        """)

        # 抽奖按钮
        lottery_button = QPushButton("开始抽奖")
        lottery_button.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        lottery_button.setStyleSheet("""
            QPushButton {
                background-color: #23ADE5; 
                color: white; 
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1E9BD4;
            }
            QPushButton:disabled {
                background-color: #AAAAAA;
            }
        """)
        lottery_button.clicked.connect(self.run_lottery)
        self.lottery_button = lottery_button

        # 结果展示
        result_label = QLabel("抽奖结果")
        result_label.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        result_label.setStyleSheet("color: #23ADE5; margin-top: 20px;")

        self.result_display = QTextEdit()
        self.result_display.setFont(QFont("Microsoft YaHei", 10))
        self.result_display.setReadOnly(True)
        self.result_display.setStyleSheet("""
            QTextEdit {
                background-color: #F8FBFD; 
                border: 1px solid #D6E9F5; 
                padding: 10px;
                border-radius: 4px;
            }
        """)

        # 添加到设置区域
        settings_layout.addLayout(file_layout)
        settings_layout.addLayout(winner_layout)
        settings_layout.addLayout(min_words_layout)
        settings_layout.addWidget(self.progress_bar)
        settings_layout.addWidget(lottery_button)
        settings_group.setLayout(settings_layout)

        # 添加到主布局
        main_layout.addWidget(title_label)
        main_layout.addWidget(settings_group)
        main_layout.addWidget(result_label)
        main_layout.addWidget(self.result_display, 1)

        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择B站评论文件", "", "Text Files (*.txt)")
        if file_path:
            self.file_path_label.setText(file_path)
            self.lottery_button.setEnabled(False)
            self.progress_bar.setFormat("加载评论中...")
            self.worker.load_comments(file_path)

    def update_progress(self, value):
        """更新进度条"""
        if value == -1:
            self.progress_bar.setFormat("加载出错!")
            QMessageBox.critical(self, "错误", "加载文件时出错!")
            self.lottery_button.setEnabled(True)
        elif value == -2:
            self.progress_bar.setFormat("发现格式错误，已跳过...")
        elif value < 100:
            self.progress_bar.setValue(value)
            self.progress_bar.setFormat(f"加载中... {value}%")
        else:
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("加载完成!")
            self.lottery_button.setEnabled(True)

    def on_loading_completed(self, comments):
        """评论加载完成回调"""
        self.comments = comments
        QMessageBox.information(self, "加载成功", f"成功加载 {len(self.comments)} 条评论!")

    def run_lottery(self):
        """启动抽奖"""
        if not self.comments:
            QMessageBox.warning(self, "警告", "请先加载评论文件!")
            return

        self.lottery_button.setEnabled(False)
        self.progress_bar.setFormat("抽奖进行中...")

        # 设置工作线程参数
        self.worker.comments = self.comments
        self.worker.min_words = self.min_words_spin.value()
        self.worker.num_winners = self.winner_spin.value()

        # 启动抽奖线程
        self.worker.run_lottery()

    def on_lottery_completed(self, winners):
        """抽奖完成回调"""
        self.lottery_button.setEnabled(True)
        self.progress_bar.setFormat("抽奖完成!")
        self.progress_bar.setValue(100)

        if not winners:
            QMessageBox.warning(self, "警告", "没有符合字数要求的评论!")
            return

        # 显示结果
        result_text = f"共 {len(self.worker.filtered_comments)} 条评论符合要求，从中抽取 {len(winners)} 位获奖者:\n\n"
        result_text += "=" * 50 + "\n\n"

        for i, winner in enumerate(winners, 1):
            result_text += f"🎉 第 {i} 位获奖者 🎉\n"
            result_text += f"用户名: {winner['username']}\n"
            result_text += f"评论内容: {winner['content']}\n"
            result_text += f"点赞数: {winner['likes']} | 评论时间: {winner['time']}\n"
            result_text += "-" * 50 + "\n\n"

        self.result_display.setPlainText(result_text)

        # 保存结果到文件
        try:
            with open("抽奖结果.txt", 'w', encoding='utf-8') as f:
                f.write(result_text)
            QMessageBox.information(self, "保存成功", "抽奖结果已保存到'抽奖结果.txt'")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"无法保存结果文件:\n{str(e)}")

    def closeEvent(self, event):
        """窗口关闭时确保线程退出"""
        self.worker_thread.quit()
        self.worker_thread.wait()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 设置全局字体
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    # 设置样式
    app.setStyleSheet("""
        QGroupBox {
            font-size: 12px;
            font-weight: bold;
            border: 1px solid #D6E9F5;
            border-radius: 6px;
            margin-top: 6px;
            background-color: #F8FBFD;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 7px;
            padding: 0 3px;
            color: #23ADE5;
        }
        QSpinBox {
            padding: 3px;
            border: 1px solid #D6E9F5;
            border-radius: 3px;
        }
        QLabel {
            color: #333;
        }
    """)

    window = CommentLotteryApp()
    window.show()
    sys.exit(app.exec_())