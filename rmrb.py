import sys
import os
import json
import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from PyPDF2 import PdfMerger, PdfReader
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QSplitter, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QListWidgetItem,
    QMessageBox, QFileDialog, QLabel
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import Qt, QUrl

# ---------------------------
# 辅助函数：自然排序（可用于部分场合）
# ---------------------------
def natural_sort_key(s):
    """
    对字符串进行自然排序：
    如果字符串中存在数字，则返回 (前缀, 数字, 后缀) 的元组；
    否则返回整个字符串的小写形式。
    """
    m = re.search(r'(\d+)', s)
    if m:
        prefix = s[:m.start()].lower()
        number = int(m.group(1))
        suffix = s[m.end():].lower()
        key = (prefix, number, suffix)
    else:
        key = (s.lower(),)
    return key

# ---------------------------
# PDF下载与合并相关函数
# ---------------------------
def fetch_pdf_links(url):
    """
    访问给定 URL，解析页面中所有 <a> 标签并提取以 .pdf 结尾的链接，
    自动转换为完整的 URL。
    """
    session = requests.Session()
    response = session.get(url)
    if response.status_code != 200:
        return []
    soup = BeautifulSoup(response.text, 'html.parser')
    pdf_links = [urljoin(url, link['href']) for link in soup.find_all('a', href=True)
                 if link['href'].lower().endswith('.pdf')]
    return pdf_links

def save_and_count_pages(pdf_url, target_folder):
    """
    将 pdf_url 对应的 PDF 下载到 target_folder，
    并使用 PyPDF2 统计页数，返回 (本地路径, 页数)；下载失败返回 None。
    """
    safe_filename = os.path.basename(pdf_url).replace('?', '').replace(':', '').replace('*', '')
    target_path = os.path.join(target_folder, safe_filename)
    if os.path.exists(target_path):
        return None
    pdf_response = requests.get(pdf_url)
    if pdf_response.status_code == 200:
        with open(target_path, 'wb') as f:
            f.write(pdf_response.content)
        with open(target_path, 'rb') as pdf_file:
            try:
                pdf_reader = PdfReader(pdf_file)
                num_pages = len(pdf_reader.pages)
            except Exception as e:
                print(f"读取PDF失败: {target_path}, 错误: {e}")
                num_pages = 0
            return (target_path, num_pages)
    else:
        return None

# ---------------------------
# 添加网址对话框
# ---------------------------
class AddWebsiteDialog(QDialog):
    def __init__(self, parent=None):
        super(AddWebsiteDialog, self).__init__(parent)
        self.setWindowTitle("添加网址")
        self.layout = QFormLayout(self)
        self.name_edit = QLineEdit(self)
        self.url_edit = QLineEdit(self)
        self.layout.addRow("按键名称:", self.name_edit)
        self.layout.addRow("网址:", self.url_edit)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.layout.addWidget(self.buttonBox)

# ---------------------------
# 修改网址对话框
# ---------------------------
class EditWebsiteDialog(QDialog):
    def __init__(self, name="", url="", parent=None):
        super(EditWebsiteDialog, self).__init__(parent)
        self.setWindowTitle("修改网址")
        self.layout = QFormLayout(self)
        self.name_edit = QLineEdit(self)
        self.name_edit.setText(name)
        self.url_edit = QLineEdit(self)
        self.url_edit.setText(url)
        self.layout.addRow("按键名称:", self.name_edit)
        self.layout.addRow("网址:", self.url_edit)
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.layout.addWidget(self.buttonBox)

# ---------------------------
# 主窗口
# ---------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        self.setWindowTitle("PDF 网页显示、爬取与合并")
        self.resize(1200, 800)
        self.websites_file = "websites.json"
        self.websites = []  # 保存网站数据，格式：{"name": 名称, "url": 网址}
        self.load_websites()

        splitter = QSplitter(Qt.Horizontal)

        # 左侧面板
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        self.list_widget = QListWidget()
        left_layout.addWidget(self.list_widget)
        self.populate_list_widget()

        # 列表项变化时加载对应网址到右侧预览区
        self.list_widget.currentItemChanged.connect(self.load_page)

        # 功能按钮布局
        btn_layout = QHBoxLayout()
        add_button = QPushButton("添加网址")
        add_button.clicked.connect(self.add_website)
        btn_layout.addWidget(add_button)

        edit_button = QPushButton("修改网址")
        edit_button.clicked.connect(self.edit_website)
        btn_layout.addWidget(edit_button)

        delete_button = QPushButton("删除网址")
        delete_button.clicked.connect(self.delete_website)
        btn_layout.addWidget(delete_button)

        left_layout.addLayout(btn_layout)

        # PDF下载（爬取版）功能
        pdf_button = QPushButton("PDF下载（爬取版）")
        pdf_button.clicked.connect(self.download_pdfs_from_list)
        left_layout.addWidget(pdf_button)

        # 右侧为网页预览窗口
        self.web_view = QWebEngineView()
        self.web_view.setUrl(QUrl("https://www.google.com"))

        splitter.addWidget(left_panel)
        splitter.addWidget(self.web_view)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def load_websites(self):
        """
        尝试从 self.websites_file 中加载已保存的网址数据，
        如果文件不存在，则使用默认数据并保存至文件。
        """
        if os.path.exists(self.websites_file):
            try:
                with open(self.websites_file, "r", encoding="utf-8") as f:
                    self.websites = json.load(f)
            except Exception as e:
                print(f"加载网址数据错误: {e}")
                self.websites = []
        else:
            # 默认使用一个预置网址
            self.websites = [{
                "name": "湖南日报",
                "url": "http://paper.people.com.cn/fcyym/pc/layout/202501/10/node_01.html"
            }]
            self.save_websites()

    def save_websites(self):
        """
        将 self.websites 列表保存至本地 JSON 文件中。
        """
        try:
            with open(self.websites_file, "w", encoding="utf-8") as f:
                json.dump(self.websites, f, ensure_ascii=False, indent=4)
            print(f"Saved websites to {self.websites_file}")
        except Exception as e:
            print(f"保存网址数据错误: {e}")

    def populate_list_widget(self):
        """
        根据 self.websites 列表填充左侧列表控件。
        """
        self.list_widget.clear()
        for entry in self.websites:
            item = QListWidgetItem(entry["name"])
            item.setData(Qt.UserRole, entry["url"])
            self.list_widget.addItem(item)

    def load_page(self, current, previous=None):
        """
        当左侧列表中选中某项时，将对应的网址加载到右侧预览窗口。
        """
        item = self.list_widget.currentItem()
        if item:
            url_str = item.data(Qt.UserRole)
            print(f"加载网址：{url_str}")
            self.web_view.load(QUrl(url_str))

    def add_website(self):
        """
        弹出添加网址对话框，添加后将新网址存入 self.websites，
        保存至文件并刷新列表，同时自动预览新添加的网址。
        """
        dialog = AddWebsiteDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            button_name = dialog.name_edit.text().strip()
            website_url = dialog.url_edit.text().strip()
            if button_name and website_url:
                new_entry = {"name": button_name, "url": website_url}
                self.websites.append(new_entry)
                self.save_websites()
                self.populate_list_widget()
                # 自动选中并加载新添加的网址
                items = self.list_widget.findItems(button_name, Qt.MatchExactly)
                if items:
                    self.list_widget.setCurrentItem(items[0])
                    self.load_page(None)

    def edit_website(self):
        """
        修改已选中的网址，弹出修改对话框预填当前数据，确认后更新 self.websites 并保存。
        """
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择一个网址")
            return
        old_name = item.text()
        old_url = item.data(Qt.UserRole)
        dialog = EditWebsiteDialog(old_name, old_url, self)
        if dialog.exec_() == QDialog.Accepted:
            new_name = dialog.name_edit.text().strip()
            new_url = dialog.url_edit.text().strip()
            if new_name and new_url:
                found = False
                for entry in self.websites:
                    if entry["name"] == old_name and entry["url"] == old_url:
                        entry["name"] = new_name
                        entry["url"] = new_url
                        found = True
                        break
                if found:
                    self.save_websites()
                    self.populate_list_widget()
                    items = self.list_widget.findItems(new_name, Qt.MatchExactly)
                    if items:
                        self.list_widget.setCurrentItem(items[0])
                        self.load_page(None)
            else:
                QMessageBox.warning(self, "错误", "名称和网址不能为空！")

    def delete_website(self):
        """
        删除已选中的网址，确认后从 self.websites 中删除该数据并保存更新。
        """
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择一个网址")
            return
        reply = QMessageBox.question(self, "确认删除", f"确认删除“{item.text()}”吗？",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            name = item.text()
            url = item.data(Qt.UserRole)
            self.websites = [entry for entry in self.websites if not (entry["name"] == name and entry["url"] == url)]
            self.save_websites()
            self.populate_list_widget()

    def crawl_pages(self, start_url):
        """
        从起始页面开始，采用宽度优先搜索爬取同栏目下所有包含 "node_" 的页面，
        并按爬取顺序返回页面 URL 列表。
        """
        visited = []
        to_visit = [start_url]
        while to_visit:
            current = to_visit.pop(0)
            if current in visited:
                continue
            visited.append(current)
            try:
                resp = requests.get(current)
                resp.raise_for_status()
                html = resp.text
                soup = BeautifulSoup(html, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if "node_" in href and ".html" in href:
                        full_url = urljoin(current, href)
                        if full_url not in visited and full_url not in to_visit:
                            to_visit.append(full_url)
            except Exception as e:
                print(f"爬取页面 {current} 失败: {e}")
        return visited

    def download_pdfs_from_list(self):
        """
        针对预览窗口当前页面：
          1. 以预览窗口当前 URL 为种子爬取同栏目下所有包含 "node_" 的页面，
          2. 按爬取顺序收集页面中的 PDF 链接，
          3. 按收集顺序下载 PDF 文件，
          4. 最后依次合并下载成功的 PDF 文件，
          5. 合并成功后删除所有下载的临时 PDF 文件。
          
         【修改说明】：
         更新 PDF 接口爬取逻辑：不再使用固定的列表项 URL，
         而是改为调用预览窗口的当前 URL（即用户更新后的日期页面）来抓取页面，
         从而确保解析到最新的 PDF 链接。
        """
        # 使用预览窗口当前加载的页面 URL 作为种子
        seed_url = self.web_view.url().toString()
        if not seed_url:
            QMessageBox.information(self, "提示", "预览页面无效。")
            return

        pages = self.crawl_pages(seed_url)
        pdf_urls = []  # 按识别顺序收集 PDF 链接
        for page in pages:
            try:
                r = requests.get(page)
                r.raise_for_status()
                html_content = r.text
            except Exception as e:
                print(f"获取页面 {page} 失败: {e}")
                continue
            soup = BeautifulSoup(html_content, "html.parser")
            for link_tag in soup.find_all("a", href=True):
                href = link_tag["href"].strip()
                if ".pdf" in href.lower():
                    full_pdf_url = urljoin(page, href)
                    if full_pdf_url not in pdf_urls:
                        pdf_urls.append(full_pdf_url)
        if not pdf_urls:
            QMessageBox.information(self, "提示", "页面中没有找到PDF链接。")
            return

        download_dir = os.path.join(os.getcwd(), "downloaded_pdfs")
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)

        pdf_files = []
        for pdf_url in pdf_urls:
            try:
                r = requests.get(pdf_url)
                r.raise_for_status()
            except Exception as e:
                print(f"下载PDF失败: {pdf_url}, 错误: {e}")
                continue
            file_name = pdf_url.split("/")[-1].split("?")[0]
            file_path = os.path.join(download_dir, file_name)
            with open(file_path, "wb") as f:
                f.write(r.content)
            pdf_files.append(file_path)
            print(f"下载完成: {pdf_url} -> {file_path}")

        if not pdf_files:
            QMessageBox.information(self, "提示", "没有成功下载任何PDF文件。")
            return

        merged_file = os.path.join(download_dir, "merged.pdf")
        try:
            merger = PdfMerger()
            for pdf_path in pdf_files:
                merger.append(pdf_path)
            merger.write(merged_file)
            merger.close()
            # 合并成功后，删除所有下载的临时PDF文件
            for pdf_path in pdf_files:
                try:
                    os.remove(pdf_path)
                    print(f"删除成功: {pdf_path}")
                except Exception as e:
                    print(f"删除文件 {pdf_path} 失败: {e}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"合并PDF失败: {e}")
            return

        QMessageBox.information(self, "完成", f"共下载 {len(pdf_files)} 个PDF文件，\n合并后的文件：\n{merged_file}\n已删除下载的临时PDF文件。")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())