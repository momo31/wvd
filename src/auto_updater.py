import os
import sys
import json
import hashlib
from pathlib import Path
import re
import threading
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen, Request
from urllib.error import URLError
import queue
import uuid
import utils


def _(message):
    return utils.trans.gettext(message)


class CancelException(Exception):
    """自定义取消异常"""
    pass

class AutoUpdater():
    def __init__(self, msg_queue: queue.Queue, github_user: str, github_repo: str, current_version: str):
        self.github_user = github_user
        self.github_repo = github_repo
        self.current_version = current_version
        self.msg_queue = msg_queue
        self.cancel_event = threading.Event()
        self.update_data = None
        self.restart_script = None
        self.protected_paths = []

    @staticmethod
    def _version_parts(value):
        match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)-momo\.(\d+)', value or '') if isinstance(value, str) else None
        return tuple(map(int, match.groups())) if match else None

    def _is_allowed_update(self, data):
        if (self.github_user, self.github_repo) != ('momo31', 'wvd') or not isinstance(data, dict):
            return False
        if self._version_parts(data.get('version')) is None or not re.fullmatch(r'[a-fA-F0-9]{32}', str(data.get('md5', ''))):
            return False
        try:
            url = urlsplit(data.get('download_url', ''))
            path = unquote(url.path)
            prefix = '/momo31/wvd/releases/download/'
            return (url.scheme == 'https' and url.netloc == 'github.com'
                    and not url.query and not url.fragment and '\\' not in path
                    and path.startswith(prefix) and '..' not in path.split('/')
                    and len(path[len(prefix):].split('/')) == 2 and path.lower().endswith('.zip'))
        except (ValueError, TypeError, AttributeError):
            return False

    def _manual_update(self):
        self.update_data = None
        self.msg_queue.put(('update_manual', {'url': 'https://github.com/momo31/wvd/releases'}))

    def can_download(self):
        return (bool(getattr(sys, 'frozen', False)) and sys.platform == 'win32'
                and self._is_allowed_update(self.update_data)
                and self._is_newer_version(self.update_data['version']))

    def _check_cancelled(self):
        if self.cancel_event.is_set():
            raise CancelException()

    def _is_newer_version(self, new_version):
        new, current = self._version_parts(new_version), self._version_parts(self.current_version)
        return bool(new is not None and current is not None and new > current)

    def check_for_updates(self):
        """执行更新检查逻辑"""
        if not getattr(sys, 'frozen', False) or (self.github_user, self.github_repo) != ('momo31', 'wvd'):
            self._manual_update()
            return
        update_url = f"https://{self.github_user}.github.io/{self.github_repo}/release.json"
        try:
            req = Request(update_url, headers={'Cache-Control': 'no-cache'})
            with urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8-sig'))
            if self.cancel_event.is_set():
                return
            if not self._is_allowed_update(data):
                self._manual_update()
                return
            
            if self._is_newer_version(data['version']):
                print(f"发现新版本: {data['version']}")
                self.update_data = data
                self.msg_queue.put(('update_available', data))

        except (URLError, OSError, ValueError, TypeError):
            if not self.cancel_event.is_set():
                self._manual_update()

    def download(self):
        try:
            self._check_cancelled()
            if not self.can_download():
                self._manual_update()
                return
            update_data = dict(self.update_data)
            # 创建临时目录
            temp_dir = str(Path(sys.executable).resolve().parent / '__update_temp__' / uuid.uuid4().hex)
            os.makedirs(temp_dir, exist_ok=True)
            
            # 下载压缩包
            download_url = update_data['download_url']
            archive_name = unquote(urlsplit(download_url).path).rsplit('/', 1)[-1]
            archive_path = os.path.join(temp_dir, archive_name)
            
            self._download_bar_and_retry(download_url,archive_path)
            self._check_cancelled()
            
            # 验证MD5
            verified = self._verify_md5(archive_path, update_data['md5'])
            self._check_cancelled()
            if not verified:
                self.msg_queue.put(('error', _("文件校验失败，请手动更新")))
                return
                
            # 解压到临时目录的子文件夹
            unpack_dir = os.path.join(temp_dir, "unpacked")
            os.makedirs(unpack_dir, exist_ok=True)
            self._extract_archive(archive_path, unpack_dir)
            self._check_cancelled()
            
            # 生成重启脚本
            restart_script = self._create_restart_script(unpack_dir)
            self._check_cancelled()
            self.restart_script = restart_script
            
            # 发送重启信号.
            self.msg_queue.put(('restart_ready', restart_script))
                
        except CancelException:
            pass
        except Exception as e:
            self.msg_queue.put(('error', _("Update failed. Please download the fork release manually.")))
        finally:
            self.msg_queue.put(('download_finished', None))
    
    def _download_bar_and_retry(self, download_url, archive_path):
        max_retries = 3
        retry_count = 0
        success = False

        while retry_count <= max_retries and not success:
            self._check_cancelled()
            try:
                # 打开网络连接
                with urlopen(download_url, timeout=15) as response:
                    self._check_cancelled()
                    # 获取文件总大小（字节）
                    total_size = int(response.headers.get('Content-Length', 0))
                    
                    self.msg_queue.put(('download_started', total_size))
                    
                    # 打开本地文件
                    with open(archive_path, 'wb') as out_file:
                        downloaded = 0
                        # 分块读取数据（每次800KB）
                        while True:
                            self._check_cancelled()
                            chunk = response.read(819200)  # 800KB缓冲区
                            self._check_cancelled()
                            if not chunk:
                                break  # 数据读取完成
                            
                            # 写入本地文件
                            out_file.write(chunk)
                            downloaded += len(chunk)
                            
                            self.msg_queue.put(('progress', downloaded))
                        
                        # 下载完成标记
                        success = True
                self.msg_queue.put(('download_complete', None))
                
            except (URLError, IOError, ConnectionResetError) as e:
                self._check_cancelled()
                # 网络或IO异常处理
                retry_count += 1
                
                if retry_count > max_retries:
                    # 重试次数耗尽，抛出原始异常
                    raise e
                else:
                    # 显示重试信息
                    print(f"下载中断，正在重试 ({retry_count}/{max_retries})...")
                    self.cancel_event.wait(2)


    def _extract_archive(self, archive_path, target_dir):
        """解压压缩包"""
        if archive_path.lower().endswith('.zip'):
            # 使用Python内置zipfile模块解压
            import zipfile
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                for member in zip_ref.infolist():
                    self._check_cancelled()
                    root = Path(target_dir).resolve()
                    name = member.filename.replace('\\', '/')
                    destination = (root / name).resolve()
                    if (name.startswith('/') or ':' in name or '..' in name.split('/')
                            or not destination.is_relative_to(root)):
                        raise ValueError('Archive member escapes the staging directory')
                    zip_ref.extract(member, target_dir)
        else:
            raise Exception(f"不支持的压缩格式: {os.path.splitext(archive_path)[1]}")

    def _verify_md5(self, file_path, expected_md5):
        """验证文件MD5哈希值"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                self._check_cancelled()
                hash_md5.update(chunk)
        return hash_md5.hexdigest() == expected_md5.lower()

    def _create_restart_script(self, unpack_dir):
        """Stage a PowerShell helper; the controller launches it after cleanup."""
        install = Path(sys.executable).resolve().parent
        stage = (install / '__update_temp__').resolve()
        unpack = Path(unpack_dir).resolve()
        if not unpack.is_relative_to(stage) or not stage.is_relative_to(install):
            raise ValueError('Update staging must be inside the installation directory')
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        protected = [install / 'config.json', *(Path(path).resolve() for path in self.protected_paths)]
        excluded = ', '.join(quote(path) for path in protected)
        script = f"""$ErrorActionPreference = 'Stop'
$installRoot = {quote(install)}
$stageRoot = {quote(stage)}
$unpackRoot = {quote(unpack)}
$protectedFiles = @({excluded})
# The old process releases its executable only after WebView has closed.
if (Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue) {{
    Wait-Process -Id {os.getpid()} -Timeout 60 -ErrorAction Stop
}}
Get-ChildItem -LiteralPath $unpackRoot -Recurse -File | ForEach-Object {{
    $relative = $_.FullName.Substring($unpackRoot.Length + 1)
    $topLevel = $relative.Split([IO.Path]::DirectorySeparatorChar)[0]
    if ($topLevel -notin @('_internal', {quote(Path(sys.executable).name)}, 'CHANGES_LOG.md')) {{ return }}
    $destination = [IO.Path]::GetFullPath((Join-Path $installRoot $relative))
    if (-not $destination.StartsWith($installRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {{ throw 'Invalid update destination' }}
    if ($protectedFiles -notcontains $destination) {{
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
    }}
}}
Start-Process -FilePath {quote(Path(sys.executable).resolve())} -WorkingDirectory $installRoot -WindowStyle Hidden
$resolvedStage = [IO.Path]::GetFullPath($stageRoot)
if ($resolvedStage -ne [IO.Path]::GetFullPath((Join-Path $installRoot '__update_temp__'))) {{ throw 'Invalid cleanup target' }}
Remove-Item -LiteralPath $resolvedStage -Recurse -Force
Remove-Item -LiteralPath $PSCommandPath -Force
"""
        path = install / '_update_restart.ps1'
        path.write_text(script, encoding='utf-8-sig')
        return str(path)
