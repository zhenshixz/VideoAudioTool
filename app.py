import os
import sys
import subprocess
import tempfile
import shutil
import tkinter as tk
from tkinter import filedialog
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__, static_folder='static', template_folder='templates')

UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), 'video_tool_uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def parse_time(time_str):
    if not time_str: return 0.0
    parts = str(time_str).split(':')
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds

def run_cmd(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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

@app.route('/api/video_info', methods=['POST'])
def video_info():
    data = request.json or {}
    filepath = data.get('filepath', '').strip().strip('"').strip("'")
    info = get_video_info(filepath)
    if info:
        return jsonify({"success": True, "info": info})
    return jsonify({"success": False, "error": "无法解析视频文件，请检查路径是否正确。"}), 400

@app.route('/api/stream')
def stream_file():
    filepath = request.args.get('path', '').strip().strip('"').strip("'")
    if os.path.exists(filepath):
        return send_file(filepath, conditional=True)
    return "File not found", 404

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "没有上传文件"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "error": "未选择文件"}), 400
    save_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(save_path)
    info = get_video_info(save_path)
    return jsonify({"success": True, "filepath": save_path, "info": info})

@app.route('/api/browse_folder', methods=['GET'])
def browse_folder():
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
    
    if not os.path.exists(filepath):
        return jsonify({"success": False, "error": "文件不存在"}), 400
        
    temp_dir = tempfile.mkdtemp(prefix="video_tool_time_")
    try:
        temp_out = os.path.join(temp_dir, "temp.mp4")
        cmd = ["ffmpeg", "-y", "-i", filepath, "-c", "copy"]
        if creation_time:
            cmd.extend(["-metadata", f"creation_time={creation_time}"])
        cmd.append(temp_out)
        run_cmd(cmd)
        
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

    if not os.path.exists(src_path):
        return jsonify({"success": False, "error": "源文件不存在"}), 400

    out_path = data.get('out_path', '').strip().strip('"').strip("'")
    
    if is_preview:
        out_path = os.path.join(tempfile.gettempdir(), "video_tool_preview.mp3")
    elif not out_path:
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
    
    if not os.path.exists(src_path):
        return jsonify({"success": False, "error": "源视频文件不存在"}), 400
    if not os.path.exists(target_path):
        return jsonify({"success": False, "error": "目标视频文件不存在"}), 400
        
    if is_preview:
        out_path = os.path.join(tempfile.gettempdir(), "video_tool_preview.mp4")
    elif not out_path:
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
        
        ext_duration = get_video_info(extracted_audio).get('duration', 0) if os.path.exists(extracted_audio) else duration
        
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

if __name__ == '__main__':
    print("启动 视频音频替换与时间修改 Web服务...")
    app.run(host='127.0.0.1', port=5000, debug=False)
