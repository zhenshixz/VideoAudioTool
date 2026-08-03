import os
import sys
import subprocess
import tempfile
import shutil
import uuid
import time
import wave
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename

if os.name == "nt":
    import tkinter as tk
    from tkinter import filedialog
else:
    tk = None
    filedialog = None

app = Flask(__name__, static_folder='static', template_folder='templates')

SERVER_MODE = os.environ.get("VIDEO_TOOL_SERVER_MODE", "0") == "1"
DATA_ROOT = os.path.abspath(
    os.environ.get(
        "VIDEO_TOOL_DATA_DIR",
        os.path.join(tempfile.gettempdir(), "video_tool_data")
    )
)
UPLOAD_FOLDER = os.path.join(DATA_ROOT, "uploads")
PREVIEW_FOLDER = os.path.join(DATA_ROOT, "previews")
EVIDENCE_LOG_FOLDER = os.path.join(DATA_ROOT, "evidence_logs")
MAX_UPLOAD_GB = int(os.environ.get("VIDEO_TOOL_MAX_UPLOAD_GB", "2"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_GB * 1024 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PREVIEW_FOLDER, exist_ok=True)
os.makedirs(EVIDENCE_LOG_FOLDER, exist_ok=True)


def is_path_allowed(filepath):
    if not SERVER_MODE:
        return True
    try:
        candidate = os.path.abspath(filepath)
        return os.path.commonpath([candidate, DATA_ROOT]) == DATA_ROOT
    except (TypeError, ValueError):
        return False


def is_preview_file(filepath):
    try:
        candidate = os.path.abspath(filepath)
        return (
            os.path.commonpath([candidate, PREVIEW_FOLDER]) == PREVIEW_FOLDER
            and os.path.isfile(candidate)
        )
    except (TypeError, ValueError):
        return False


def require_existing_file(filepath):
    return bool(filepath and is_path_allowed(filepath) and os.path.isfile(filepath))


def make_preview_path(suffix):
    # cleanup_old_files may remove empty runtime subdirectories. Recreate the
    # preview directory at the point of use so FFmpeg always has a valid target.
    os.makedirs(PREVIEW_FOLDER, exist_ok=True)
    return os.path.join(PREVIEW_FOLDER, f"{uuid.uuid4().hex}{suffix}")


def cleanup_old_files(max_age_hours=24):
    cutoff = time.time() - max_age_hours * 3600
    for root, dirs, files in os.walk(DATA_ROOT, topdown=False):
        for filename in files:
            path = os.path.join(root, filename)
            if os.path.commonpath([os.path.abspath(path), EVIDENCE_LOG_FOLDER]) == EVIDENCE_LOG_FOLDER:
                continue
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass
        for dirname in dirs:
            path = os.path.join(root, dirname)
            try:
                if path not in {UPLOAD_FOLDER, PREVIEW_FOLDER, EVIDENCE_LOG_FOLDER} and not os.listdir(path):
                    os.rmdir(path)
            except OSError:
                pass


cleanup_old_files()
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PREVIEW_FOLDER, exist_ok=True)
os.makedirs(EVIDENCE_LOG_FOLDER, exist_ok=True)

def parse_time(time_str):
    if not time_str: return 0.0
    parts = str(time_str).split(':')
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds

def run_cmd(cmd):
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace"
    )
    if result.returncode != 0:
        details = (result.stderr or "FFmpeg execution failed").strip()
        raise RuntimeError(details[-2000:])


def run_capture(cmd, timeout=30):
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("命令执行超时，请重新连接手机后再试。") from e
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "命令执行失败").strip()
        raise RuntimeError(details[-2000:])
    return result.stdout.strip()


def find_adb():
    configured = os.environ.get("VIDEO_TOOL_ADB_PATH", "").strip()
    candidates = [
        configured,
        shutil.which("adb"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "platform-tools", "adb.exe")
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


def get_phone_status():
    adb_path = find_adb()
    if not adb_path:
        return {
            "success": False,
            "state": "adb_missing",
            "error": "尚未安装 Android 手机连接组件。"
        }

    try:
        output = run_capture([adb_path, "devices", "-l"], timeout=12)
    except Exception as e:
        return {"success": False, "state": "adb_error", "error": str(e), "adb_path": adb_path}

    devices = []
    for line in output.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        serial = parts[0]
        state = parts[1] if len(parts) > 1 else "unknown"
        devices.append({"serial": serial, "state": state})

    if not devices:
        return {
            "success": False,
            "state": "disconnected",
            "error": "未检测到手机。请连接数据线、选择文件传输并开启 USB 调试。",
            "adb_path": adb_path
        }
    if len(devices) > 1:
        return {
            "success": False,
            "state": "multiple",
            "error": "检测到多台 Android 设备，请只保留一台手机连接。",
            "devices": devices,
            "adb_path": adb_path
        }

    device = devices[0]
    if device["state"] == "unauthorized":
        return {
            "success": False,
            "state": "unauthorized",
            "error": "手机尚未授权。请解锁手机，在“允许 USB 调试”弹窗中点击允许。",
            "serial": device["serial"],
            "adb_path": adb_path
        }
    if device["state"] != "device":
        return {
            "success": False,
            "state": device["state"],
            "error": f"手机连接状态异常：{device['state']}。请重新插拔数据线。",
            "serial": device["serial"],
            "adb_path": adb_path
        }

    serial = device["serial"]
    def getprop(name):
        try:
            return run_capture([adb_path, "-s", serial, "shell", "getprop", name], timeout=8)
        except Exception:
            return ""

    return {
        "success": True,
        "state": "connected",
        "serial": serial,
        "model": getprop("ro.product.model") or "Android",
        "android": getprop("ro.build.version.release"),
        "coloros": getprop("ro.build.version.oplusrom") or getprop("ro.build.version.opporom"),
        "adb_path": adb_path
    }


def sha256_file(filepath):
    digest = hashlib.sha256()
    with open(filepath, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_wave_frames(reader, writer, frame_count, chunk_frames=65536):
    remaining = max(0, int(frame_count))
    while remaining > 0:
        data = reader.readframes(min(chunk_frames, remaining))
        if not data:
            break
        frame_size = reader.getnchannels() * reader.getsampwidth()
        frames_read = len(data) // frame_size
        writer.writeframesraw(data)
        remaining -= frames_read
    return frame_count - remaining


def build_filled_audio(base_path, clip_path, output_path, start_seconds, mode, original_gap_seconds):
    with wave.open(base_path, "rb") as base_audio, \
            wave.open(clip_path, "rb") as clip_audio, \
            wave.open(output_path, "wb") as output_audio:
        base_format = (
            base_audio.getnchannels(), base_audio.getsampwidth(), base_audio.getframerate()
        )
        clip_format = (
            clip_audio.getnchannels(), clip_audio.getsampwidth(), clip_audio.getframerate()
        )
        if base_format != clip_format:
            raise RuntimeError("内部音频格式不一致，无法完成拼接。")

        total_frames = base_audio.getnframes()
        clip_frames = clip_audio.getnframes()
        if clip_frames <= 0:
            raise RuntimeError("选择的 MP3 片段没有可用音频。")

        frame_rate = base_audio.getframerate()
        start_frame = min(total_frames, max(0, round(start_seconds * frame_rate)))
        gap_frames = max(0, round(original_gap_seconds * frame_rate))
        output_audio.setparams(base_audio.getparams())

        copy_wave_frames(base_audio, output_audio, start_frame)
        position = start_frame

        while position < total_frames:
            insert_frames = min(clip_frames, total_frames - position)
            clip_audio.rewind()
            written = copy_wave_frames(clip_audio, output_audio, insert_frames)
            if written <= 0:
                raise RuntimeError("MP3 片段写入失败。")
            position += written
            base_audio.setpos(position)

            if mode == "preserve_once":
                copy_wave_frames(base_audio, output_audio, total_frames - position)
                position = total_frames
                break

            original_frames = min(gap_frames, total_frames - position)
            if original_frames > 0:
                copied = copy_wave_frames(base_audio, output_audio, original_frames)
                position += copied

        output_audio.writeframes(b"")

def get_video_info(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", 
            "format=duration,size:stream=width,height,codec_type", 
            "-of", "json", filepath
        ], stderr=subprocess.DEVNULL).decode('utf-8')
        import json
        data = json.loads(out)
        duration = float(data.get('format', {}).get('duration', 0))
        size = int(data.get('format', {}).get('size', 0))
        width, height = 0, 0
        has_audio = False
        for s in data.get('streams', []):
            if s.get('codec_type') == 'video':
                width = s.get('width', 0)
                height = s.get('height', 0)
            elif s.get('codec_type') == 'audio':
                has_audio = True
        
        ctime = os.path.getctime(filepath)
        ctime_str = datetime.fromtimestamp(ctime).strftime('%Y-%m-%d %H:%M:%S')
        
        return {
            "duration": duration,
            "size": size,
            "width": width,
            "height": height,
            "has_audio": has_audio,
            "creation_time": ctime_str
        }
    except Exception as e:
        print(f"Error getting video info: {e}")
        return None

def modify_creation_time(filepath, time_str):
    try:
        dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        ts = dt.timestamp()
        os.utime(filepath, (ts, ts))
        if os.name == "nt":
            safe_path = filepath.replace("'", "''")
            ps_cmd = f"(Get-Item '{safe_path}').CreationTime = [datetime]::ParseExact('{time_str}', 'yyyy-MM-dd HH:mm:ss', $null)"
            subprocess.run(["powershell", "-Command", ps_cmd], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"Failed to modify creation time: {e}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/health')
def health():
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    ffprobe_ok = shutil.which("ffprobe") is not None
    status = 200 if ffmpeg_ok and ffprobe_ok else 503
    return jsonify({
        "success": status == 200,
        "server_mode": SERVER_MODE,
        "ffmpeg": ffmpeg_ok,
        "ffprobe": ffprobe_ok
    }), status


@app.route('/api/phone/status')
def phone_status():
    if SERVER_MODE or request.remote_addr not in {"127.0.0.1", "::1"}:
        return jsonify({
            "success": False,
            "state": "local_only",
            "error": "手机连接功能只能在运行服务的电脑本机使用。"
        }), 403
    status = get_phone_status()
    return jsonify(status), 200 if status.get("success") else 400


@app.route('/api/phone/open_installer', methods=['POST'])
def open_phone_installer():
    if SERVER_MODE or request.remote_addr not in {"127.0.0.1", "::1"}:
        return jsonify({"success": False, "error": "该操作只能在本机使用。"}), 403
    installer = os.path.join(os.path.dirname(os.path.abspath(__file__)), "install-phone-tools.bat")
    if os.name != "nt" or not os.path.isfile(installer):
        return jsonify({"success": False, "error": "未找到 Windows 手机连接组件安装脚本。"}), 404
    try:
        os.startfile(installer)
        return jsonify({"success": True})
    except OSError as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/phone/fix_video_time', methods=['POST'])
def fix_phone_video_time():
    if SERVER_MODE or request.remote_addr not in {"127.0.0.1", "::1"}:
        return jsonify({"success": False, "error": "该操作只能在连接手机的电脑本机使用。"}), 403

    data = request.json or {}
    filepath = data.get('filepath', '').strip().strip('"').strip("'")
    event_time = data.get('event_time', '').strip()
    confirmed = data.get('confirmed_true_time', False)
    if not confirmed:
        return jsonify({"success": False, "error": "请先确认填写的是实际事件发生时间。"}), 400
    if not require_existing_file(filepath):
        return jsonify({"success": False, "error": "待写入手机的视频不存在或已失效。"}), 400

    try:
        local_dt = datetime.strptime(event_time, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return jsonify({"success": False, "error": "时间格式必须为 YYYY-MM-DD HH:MM:SS。"}), 400

    phone = get_phone_status()
    if not phone.get("success"):
        return jsonify(phone), 400

    beijing_tz = timezone(timedelta(hours=8))
    aware_dt = local_dt.replace(tzinfo=beijing_tz)
    event_epoch = int(aware_dt.timestamp())
    event_epoch_ms = event_epoch * 1000
    utc_creation_time = aware_dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000000Z')
    serial = phone["serial"]
    adb_path = phone["adb_path"]
    remote_dir = "/sdcard/DCIM/VideoEvidence"
    remote_name = f"evidence_{local_dt.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4"
    remote_path = f"{remote_dir}/{remote_name}"

    temp_dir = tempfile.mkdtemp(prefix="video_tool_phone_time_")
    corrected_path = os.path.join(temp_dir, remote_name)
    try:
        run_cmd([
            "ffmpeg", "-y", "-i", filepath,
            "-map", "0", "-map_metadata", "0", "-c", "copy",
            "-metadata", f"creation_time={utc_creation_time}",
            "-metadata:s:v:0", f"creation_time={utc_creation_time}",
            "-metadata:s:a:0", f"creation_time={utc_creation_time}",
            corrected_path
        ])
        os.utime(corrected_path, (event_epoch, event_epoch))
        if os.name == "nt":
            modify_creation_time(corrected_path, event_time)

        source_hash = sha256_file(filepath)
        corrected_hash = sha256_file(corrected_path)

        run_capture([adb_path, "-s", serial, "shell", "mkdir", "-p", remote_dir], timeout=15)
        run_capture([adb_path, "-s", serial, "push", corrected_path, remote_path], timeout=300)

        try:
            run_capture([
                adb_path, "-s", serial, "shell", "touch", "-m", "-d", f"@{event_epoch}", remote_path
            ], timeout=15)
        except Exception:
            touch_value = local_dt.strftime('%Y%m%d%H%M.%S')
            run_capture([
                adb_path, "-s", serial, "shell", "touch", "-m", "-t", touch_value, remote_path
            ], timeout=15)

        phone_hash = ""
        try:
            phone_hash_output = run_capture([
                adb_path, "-s", serial, "shell", "sha256sum", remote_path
            ], timeout=120)
            phone_hash = phone_hash_output.split()[0].lower()
        except Exception:
            pass

        run_capture([
            adb_path, "-s", serial, "shell", "am", "broadcast",
            "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
            "-d", f"file://{remote_path}"
        ], timeout=20)
        time.sleep(2)

        where_clause = f"_display_name='{remote_name}'"
        media_output = ""
        media_date_taken = None
        query_cmd = [
            adb_path, "-s", serial, "shell", "content", "query",
            "--uri", "content://media/external/video/media",
            "--projection", "_id:_display_name:datetaken:date_modified",
            "--where", where_clause
        ]
        try:
            media_output = run_capture(query_cmd, timeout=20)
            match = re.search(r"datetaken=(\d+)", media_output)
            if match:
                media_date_taken = int(match.group(1))
        except Exception:
            pass

        gallery_time_verified = (
            media_date_taken is not None
            and abs(media_date_taken - event_epoch_ms) <= 2000
        )
        if not gallery_time_verified:
            try:
                run_capture([
                    adb_path, "-s", serial, "shell", "content", "update",
                    "--uri", "content://media/external/video/media",
                    "--bind", f"datetaken:l:{event_epoch_ms}",
                    "--where", where_clause
                ], timeout=20)
                media_output = run_capture(query_cmd, timeout=20)
                match = re.search(r"datetaken=(\d+)", media_output)
                if match:
                    media_date_taken = int(match.group(1))
                    gallery_time_verified = abs(media_date_taken - event_epoch_ms) <= 2000
            except Exception:
                pass

        phone_mtime = None
        try:
            phone_mtime = int(run_capture([
                adb_path, "-s", serial, "shell", "stat", "-c", "%Y", remote_path
            ], timeout=15).splitlines()[-1])
        except Exception:
            pass

        record = {
            "record_type": "phone_video_event_time_correction",
            "operation_time_beijing": datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S'),
            "declared_event_time_beijing": event_time,
            "source_path": filepath,
            "source_sha256": source_hash,
            "corrected_sha256": corrected_hash,
            "phone_sha256": phone_hash or None,
            "phone_path": remote_path,
            "device": {
                "serial": serial,
                "model": phone.get("model"),
                "android": phone.get("android"),
                "coloros": phone.get("coloros")
            },
            "verification": {
                "phone_hash_matches": bool(phone_hash and phone_hash == corrected_hash),
                "phone_mtime_epoch": phone_mtime,
                "phone_mtime_matches": phone_mtime is not None and abs(phone_mtime - event_epoch) <= 2,
                "media_date_taken_epoch_ms": media_date_taken,
                "gallery_time_verified": gallery_time_verified,
                "media_query": media_output
            }
        }
        log_name = f"phone_time_{local_dt.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
        log_path = os.path.join(EVIDENCE_LOG_FOLDER, log_name)
        with open(log_path, "w", encoding="utf-8") as log_file:
            json.dump(record, log_file, ensure_ascii=False, indent=2)

        return jsonify({
            "success": True,
            "phone_path": remote_path,
            "event_time": event_time,
            "device": record["device"],
            "source_sha256": source_hash,
            "corrected_sha256": corrected_hash,
            "phone_hash_matches": record["verification"]["phone_hash_matches"],
            "phone_mtime_matches": record["verification"]["phone_mtime_matches"],
            "gallery_time_verified": gallery_time_verified,
            "media_date_taken_epoch_ms": media_date_taken,
            "log_path": log_path,
            "warning": None if gallery_time_verified else "文件时间已写入，但未能从手机媒体库确认相册时间，请在 OPPO 图库中刷新后核对。"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify({
        "success": False,
        "error": f"文件过大，单个文件不能超过 {MAX_UPLOAD_GB} GB。"
    }), 413

@app.route('/api/video_info', methods=['POST'])
def video_info():
    data = request.json or {}
    filepath = data.get('filepath', '').strip().strip('"').strip("'")
    if not require_existing_file(filepath):
        return jsonify({"success": False, "error": "文件不存在或无权访问。"}), 400
    info = get_video_info(filepath)
    if info:
        return jsonify({"success": True, "info": info})
    return jsonify({"success": False, "error": "无法解析视频文件，请检查路径是否正确。"}), 400

@app.route('/api/stream')
def stream_file():
    filepath = request.args.get('path', '').strip().strip('"').strip("'")
    if require_existing_file(filepath):
        return send_file(filepath, conditional=True)
    return "File not found or access denied", 404


@app.route('/api/delete_preview', methods=['POST'])
def delete_preview():
    filepath = (request.json or {}).get('filepath', '')
    if not is_preview_file(filepath):
        return jsonify({"success": False, "error": "预览文件不存在或路径无效。"}), 404
    try:
        os.remove(filepath)
        return jsonify({"success": True})
    except OSError as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "没有上传文件"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "error": "未选择文件"}), 400
    safe_name = secure_filename(file.filename)
    if not safe_name:
        safe_name = f"upload_{uuid.uuid4().hex}.bin"
    upload_dir = os.path.join(UPLOAD_FOLDER, uuid.uuid4().hex)
    os.makedirs(upload_dir, exist_ok=True)
    save_path = os.path.join(upload_dir, safe_name)
    file.save(save_path)
    info = get_video_info(save_path)
    if not info:
        shutil.rmtree(upload_dir, ignore_errors=True)
        return jsonify({"success": False, "error": "上传的文件不是可解析的音视频文件。"}), 400
    return jsonify({"success": True, "filepath": save_path, "info": info})

@app.route('/api/browse_folder', methods=['GET'])
def browse_folder():
    if SERVER_MODE or not tk or not filedialog:
        return jsonify({
            "success": False,
            "error": "服务器模式不支持选择服务器目录，请上传文件后直接下载处理结果。"
        }), 400
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        folder_path = filedialog.askdirectory(parent=root, title="选择导出文件夹")
        root.destroy()
        return jsonify({"success": True, "path": folder_path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/modify_time_only', methods=['POST'])
def modify_time_only():
    data = request.json or {}
    filepath = data.get('filepath', '').strip().strip('"').strip("'")
    creation_time = data.get('creation_time', '').strip()
    overwrite = data.get('overwrite', False)
    
    if not require_existing_file(filepath):
        return jsonify({"success": False, "error": "文件不存在"}), 400
        
    temp_dir = tempfile.mkdtemp(prefix="video_tool_time_")
    try:
        source_ext = os.path.splitext(filepath)[1] or ".mp4"
        temp_out = os.path.join(temp_dir, f"temp{source_ext}")
        cmd = ["ffmpeg", "-y", "-i", filepath, "-c", "copy"]
        if creation_time:
            cmd.extend(["-metadata", f"creation_time={creation_time}"])
        cmd.append(temp_out)
        run_cmd(cmd)
        
        if SERVER_MODE:
            overwrite = False

        if overwrite:
            final_out = filepath
        else:
            base, ext = os.path.splitext(filepath)
            final_out = f"{base}_time_modified{ext}"
            
        # Instead of shutil.move which might fail across drives, we use copy2
        shutil.copy2(temp_out, final_out)
        
        if creation_time:
            modify_creation_time(final_out, creation_time)
            
        shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({"success": True, "out_path": final_out})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/export_mp3', methods=['POST'])
def export_mp3():
    data = request.json or {}
    src_path = data.get('src_path', '').strip().strip('"').strip("'")
    src_start = float(data.get('src_start', 0))
    duration = float(data.get('duration', 0))
    is_preview = data.get('is_preview', False)

    if not require_existing_file(src_path):
        return jsonify({"success": False, "error": "源文件不存在"}), 400

    out_path = data.get('out_path', '').strip().strip('"').strip("'")
    
    if is_preview:
        out_path = make_preview_path(".mp3")
    elif SERVER_MODE or not out_path:
        out_dir = os.path.dirname(src_path) or os.getcwd()
        base = os.path.splitext(os.path.basename(src_path))[0]
        out_path = os.path.join(out_dir, f"{base}_extracted.mp3")

    try:
        cmd_extract = ["ffmpeg", "-y", "-i", src_path, "-ss", str(src_start)]
        if duration > 0:
            cmd_extract.extend(["-t", str(duration)])
        cmd_extract.extend(["-vn", "-ac", "2", "-ar", "44100", "-b:a", "192k", out_path])
        run_cmd(cmd_extract)
        return jsonify({"success": True, "out_path": out_path, "is_preview": is_preview})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/process', methods=['POST'])
def process_video():
    data = request.json or {}
    src_path = data.get('src_path', '').strip().strip('"').strip("'")
    src_start = float(data.get('src_start', 0))
    duration = float(data.get('duration', 0))
    
    target_path = data.get('target_path', '').strip().strip('"').strip("'")
    replace_mode = data.get('replace_mode', 'full')
    target_start = float(data.get('target_start', 0))
    
    out_path = data.get('out_path', '').strip().strip('"').strip("'")
    creation_time = data.get('creation_time', '').strip()
    is_preview = data.get('is_preview', False)
    
    if not require_existing_file(src_path):
        return jsonify({"success": False, "error": f"源视频文件不存在: [{src_path}]"}), 400
    if not require_existing_file(target_path):
        return jsonify({"success": False, "error": "目标视频文件不存在"}), 400
        
    if is_preview:
        out_path = make_preview_path(".mp4")
    elif SERVER_MODE or not out_path:
        out_dir = os.path.dirname(target_path) or os.getcwd()
        out_path = os.path.join(out_dir, f"edited_{os.path.basename(target_path)}")

    temp_dir = tempfile.mkdtemp(prefix="video_tool_proc_")
    try:
        extracted_audio = os.path.join(temp_dir, "extracted.wav")
        cmd_extract = ["ffmpeg", "-y", "-i", src_path, "-ss", str(src_start)]
        if duration > 0:
            cmd_extract.extend(["-t", str(duration)])
        cmd_extract.extend(["-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", extracted_audio])
        run_cmd(cmd_extract)
        
        extracted_info = get_video_info(extracted_audio) if os.path.exists(extracted_audio) else None
        ext_duration = extracted_info.get('duration', duration) if extracted_info else duration
        
        if replace_mode == 'segment' and target_start >= 0:
            audio_before = os.path.join(temp_dir, "before.wav")
            audio_after = os.path.join(temp_dir, "after.wav")
            
            if target_start > 0:
                run_cmd(["ffmpeg", "-y", "-i", target_path, "-t", str(target_start), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", audio_before])
            
            target_info = get_video_info(target_path) or {}
            target_dur = target_info.get('duration', 0)
            
            resume_time = target_start + ext_duration
            
            has_after = resume_time < target_dur
            if has_after:
                run_cmd(["ffmpeg", "-y", "-i", target_path, "-ss", str(resume_time), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", audio_after])

            def safe_path(p): return p.replace('\\', '/')
            
            concat_list = os.path.join(temp_dir, "concat.txt")
            with open(concat_list, "w", encoding='utf-8') as f:
                if target_start > 0 and os.path.exists(audio_before):
                    f.write(f"file '{safe_path(audio_before)}'\n")
                f.write(f"file '{safe_path(extracted_audio)}'\n")
                if has_after and os.path.exists(audio_after):
                    f.write(f"file '{safe_path(audio_after)}'\n")

            merged_audio = os.path.join(temp_dir, "merged.wav")
            run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", merged_audio])
            
            run_cmd(["ffmpeg", "-y", "-i", target_path, "-i", merged_audio, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-af", "apad", "-map", "0:v:0", "-map", "1:a:0", "-shortest", out_path])
        else:
            run_cmd(["ffmpeg", "-y", "-i", target_path, "-i", extracted_audio, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-af", "apad", "-map", "0:v:0", "-map", "1:a:0", "-shortest", out_path])
            
        time_modified = False
        if not is_preview and creation_time:
            temp_out = os.path.join(temp_dir, "temp_out.mp4")
            shutil.move(out_path, temp_out)
            run_cmd([
                "ffmpeg", "-y", "-i", temp_out,
                "-c", "copy",
                "-metadata", f"creation_time={creation_time}",
                out_path
            ])
            modify_creation_time(out_path, creation_time)
            time_modified = True
            
        return jsonify({
            "success": True, 
            "out_path": out_path, 
            "time_modified": time_modified,
            "is_preview": is_preview
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.route('/api/fill_audio', methods=['POST'])
def fill_audio():
    data = request.json or {}
    src_path = data.get('src_path', '').strip().strip('"').strip("'")
    target_path = data.get('target_path', '').strip().strip('"').strip("'")
    mode = data.get('mode', 'preserve_once')
    is_preview = data.get('is_preview', False)

    try:
        src_start = float(data.get('src_start', 0))
        duration = float(data.get('duration', 0))
        target_start = float(data.get('target_start', 0))
        original_gap = float(data.get('original_gap', 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "时间参数格式不正确。"}), 400

    if not require_existing_file(src_path):
        return jsonify({"success": False, "error": "导入的 MP3 不存在或已失效。"}), 400
    if not require_existing_file(target_path):
        return jsonify({"success": False, "error": "目标视频不存在或已失效。"}), 400
    if mode not in {"preserve_once", "repeat_with_original_gap"}:
        return jsonify({"success": False, "error": "不支持的填充模式。"}), 400
    if min(src_start, duration, target_start, original_gap) < 0:
        return jsonify({"success": False, "error": "时间参数不能为负数。"}), 400

    src_info = get_video_info(src_path) or {}
    target_info = get_video_info(target_path) or {}
    src_duration = float(src_info.get('duration', 0))
    target_duration = float(target_info.get('duration', 0))
    if not src_info.get('has_audio') or src_duration <= 0:
        return jsonify({"success": False, "error": "导入文件没有可用音频。"}), 400
    if target_duration <= 0:
        return jsonify({"success": False, "error": "无法获取目标视频时长。"}), 400
    if src_start >= src_duration:
        return jsonify({"success": False, "error": "MP3 片段开始时间超出音频时长。"}), 400
    if target_start > target_duration:
        return jsonify({"success": False, "error": "首次插入起点超出视频时长。"}), 400

    available_duration = src_duration - src_start
    clip_duration = min(duration if duration > 0 else available_duration, available_duration)
    if clip_duration <= 0:
        return jsonify({"success": False, "error": "请选择有效的 MP3 时间片段。"}), 400

    out_path = data.get('out_path', '').strip().strip('"').strip("'")
    if is_preview:
        out_path = make_preview_path(".mp4")
    elif SERVER_MODE or not out_path:
        out_dir = os.path.dirname(target_path) or os.getcwd()
        base, ext = os.path.splitext(os.path.basename(target_path))
        out_path = os.path.join(out_dir, f"{base}_mp3_filled{ext or '.mp4'}")
    elif not os.path.isdir(os.path.dirname(os.path.abspath(out_path))):
        return jsonify({"success": False, "error": "导出文件夹不存在，请重新选择。"}), 400

    temp_dir = tempfile.mkdtemp(prefix="video_tool_fill_")
    try:
        base_audio = os.path.join(temp_dir, "base.wav")
        clip_audio = os.path.join(temp_dir, "clip.wav")
        filled_audio = os.path.join(temp_dir, "filled.wav")

        if target_info.get('has_audio'):
            run_cmd([
                "ffmpeg", "-y", "-i", target_path,
                "-vn", "-af", "aresample=async=1:first_pts=0,apad",
                "-t", str(target_duration),
                "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", base_audio
            ])
        else:
            run_cmd([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-t", str(target_duration), "-c:a", "pcm_s16le", base_audio
            ])

        run_cmd([
            "ffmpeg", "-y", "-i", src_path,
            "-ss", str(src_start), "-t", str(clip_duration),
            "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", clip_audio
        ])

        build_filled_audio(
            base_audio,
            clip_audio,
            filled_audio,
            target_start,
            mode,
            original_gap
        )

        run_cmd([
            "ffmpeg", "-y", "-i", target_path, "-i", filled_audio,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0", "-shortest", out_path
        ])

        return jsonify({
            "success": True,
            "out_path": out_path,
            "is_preview": is_preview,
            "mode": mode
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.route('/api/boost_volume', methods=['POST'])
def boost_volume():
    data = request.json or {}
    src_path = data.get('src_path', '').strip().strip('"').strip("'")
    volume_db = float(data.get('volume_db', 0.0))
    out_path = data.get('out_path', '').strip().strip('"').strip("'")
    is_preview = data.get('is_preview', False)
    
    if not require_existing_file(src_path):
        return jsonify({"success": False, "error": f"源视频文件不存在: [{src_path}]"}), 400
        
    if is_preview:
        out_path = make_preview_path(".mp4")
    elif SERVER_MODE or not out_path:
        out_dir = os.path.dirname(src_path) or os.getcwd()
        base, ext = os.path.splitext(os.path.basename(src_path))
        out_path = os.path.join(out_dir, f"{base}_boosted{ext}")

    temp_dir = tempfile.mkdtemp(prefix="video_tool_vol_")
    try:
        temp_out = os.path.join(temp_dir, "temp_out" + os.path.splitext(src_path)[1])
        cmd = ["ffmpeg", "-y", "-i", src_path]
        
        if is_preview:
            cmd.extend(["-t", "10"])
            
        cmd.extend([
            "-c:v", "copy",
            "-af", f"volume={volume_db}dB,alimiter=limit=0.99",
            "-c:a", "aac", "-b:a", "192k",
            temp_out
        ])
        
        run_cmd(cmd)
        shutil.copy2(temp_out, out_path)
        
        if not is_preview:
            orig_info = get_video_info(src_path)
            if orig_info and orig_info.get('creation_time'):
                modify_creation_time(out_path, orig_info['creation_time'])
            
        return jsonify({"success": True, "out_path": out_path, "is_preview": is_preview})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.route('/api/open_location', methods=['POST'])
def open_location():
    if SERVER_MODE or os.name != "nt":
        return jsonify({
            "success": False,
            "error": "服务器模式不能打开服务器目录，请使用下载按钮。"
        }), 400
    data = request.json or {}
    filepath = data.get('filepath', '').strip().strip('"').strip("'")
    
    if not filepath:
        return jsonify({"success": False, "error": "路径为空"}), 400
        
    try:
        # Windows explorer 要求严格的反斜杠规范
        filepath = os.path.normpath(filepath)
        
        if os.path.exists(filepath):
            if os.path.isdir(filepath):
                subprocess.run(f'explorer "{filepath}"', shell=True)
            else:
                subprocess.run(f'explorer /select,"{filepath}"', shell=True)
            return jsonify({"success": True})
        else:
            parent = os.path.dirname(filepath)
            if os.path.exists(parent):
                subprocess.run(f'explorer "{parent}"', shell=True)
                return jsonify({"success": True})
            return jsonify({"success": False, "error": "路径及其父目录均不存在"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/download', methods=['GET'])
def download_file():
    filepath = request.args.get('path')
    if not require_existing_file(filepath):
        return "File not found or access denied", 404
    return send_file(filepath, as_attachment=True)


if __name__ == '__main__':
    print("启动 视频音频替换与时间修改 Web服务...")
    app.run(host='127.0.0.1', port=5000, debug=False)
