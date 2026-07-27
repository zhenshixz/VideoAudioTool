import argparse
import subprocess
import os
import tempfile
import shutil
import sys
from datetime import datetime

def parse_time(time_str):
    if not time_str: return 0
    parts = str(time_str).split(':')
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds

def run_cmd(cmd):
    # print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def get_duration(filepath):
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration", 
            "-of", "default=noprint_wrappers=1:nokey=1", filepath
        ], stderr=subprocess.DEVNULL).decode().strip()
        return float(out) if out != 'N/A' else 0.0
    except:
        return 0.0

def modify_times(filepath, time_str):
    try:
        dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        ts = dt.timestamp()
        # Modifies access and modified time
        os.utime(filepath, (ts, ts))
        # Modifies creation time via PowerShell
        ps_cmd = f"(Get-Item '{filepath}').CreationTime = [datetime]::ParseExact('{time_str}', 'yyyy-MM-dd HH:mm:ss', $null)"
        subprocess.run(["powershell", "-Command", ps_cmd], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[*] 时间已成功修改为: {time_str}")
    except Exception as e:
        print(f"[!] 修改时间失败: {e}")

def main():
    parser = argparse.ArgumentParser(description="视频音频替换与时间修改工具")
    parser.add_argument('--src', help="提供音频的源视频文件路径")
    parser.add_argument('--src-start', default="0", help="源视频音频的起始提取时间 (例如: 0 或 00:01:20)")
    parser.add_argument('--duration', help="需要提取的音频持续时间 (留空表示一直到结尾)")
    parser.add_argument('--target', help="需要被替换音频的目标视频文件路径")
    parser.add_argument('--target-start', help="目标视频中要开始替换的起始时间 (留空表示替换整个音频轨)")
    parser.add_argument('--out', help="输出的视频文件路径")
    parser.add_argument('--time', help="新视频的创建时间 (格式: YYYY-MM-DD HH:MM:SS, 留空表示不修改)")
    
    args = parser.parse_args()
    
    # Interactive mode if no args provided
    if len(sys.argv) == 1:
        print("="*40)
        print("       视频音频替换与时间修改工具")
        print("="*40)
        args.src = input("1. 源视频路径 (拖拽文件到此): ").strip().strip('"').strip("'")
        args.src_start = input("2. 提取起始时间 [默认 0]: ").strip() or "0"
        args.duration = input("3. 提取持续时间 [留空提取到尾]: ").strip()
        args.target = input("4. 目标视频路径 (拖拽文件到此): ").strip().strip('"').strip("'")
        args.target_start = input("5. 目标替换起始时间 [留空则替换全部音频]: ").strip()
        args.out = input("6. 输出文件路径 (例如 out.mp4): ").strip().strip('"').strip("'")
        args.time = input("7. 设置创建时间 [格式 YYYY-MM-DD HH:MM:SS, 留空不修改]: ").strip()
        print("="*40)
        
    # Validation
    if not args.src or not os.path.exists(args.src):
        print(f"[!] 源视频不存在或路径为空: {args.src}")
        if len(sys.argv) == 1: input("按回车键退出...")
        return
    if not args.target or not os.path.exists(args.target):
        print(f"[!] 目标视频不存在或路径为空: {args.target}")
        if len(sys.argv) == 1: input("按回车键退出...")
        return
    if not args.out:
        print("[!] 输出路径为空")
        if len(sys.argv) == 1: input("按回车键退出...")
        return
        
    temp_dir = tempfile.mkdtemp(prefix="video_tool_")
    try:
        print("[*] 正在从源视频提取音频...")
        extracted_audio = os.path.join(temp_dir, "extracted.wav")
        cmd_extract = ["ffmpeg", "-y", "-i", args.src, "-ss", args.src_start]
        if args.duration:
            cmd_extract.extend(["-t", args.duration])
        # Force stereo, 44.1kHz, s16le PCM to be safe for concatenation
        cmd_extract.extend(["-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", extracted_audio])
        run_cmd(cmd_extract)
        
        if args.target_start:
            print("[*] 正在目标视频中替换指定时段音频...")
            target_start_sec = parse_time(args.target_start)
            ext_duration = get_duration(extracted_audio)
            
            audio_before = os.path.join(temp_dir, "before.wav")
            audio_after = os.path.join(temp_dir, "after.wav")
            
            # Extract before
            if target_start_sec > 0:
                run_cmd(["ffmpeg", "-y", "-i", args.target, "-t", str(target_start_sec), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", audio_before])
            
            # Extract after
            resume_time = target_start_sec + ext_duration
            target_duration = get_duration(args.target)
            
            has_after = resume_time < target_duration
            if has_after:
                run_cmd(["ffmpeg", "-y", "-i", args.target, "-ss", str(resume_time), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", audio_after])
            
            # Concat
            print("[*] 正在合并音频流...")
            concat_list = os.path.join(temp_dir, "concat.txt")
            with open(concat_list, "w", encoding="utf-8") as f:
                if target_start_sec > 0 and os.path.exists(audio_before):
                    f.write(f"file '{audio_before.replace(chr(92), '/')}'\n")
                f.write(f"file '{extracted_audio.replace(chr(92), '/')}'\n")
                if has_after and os.path.exists(audio_after):
                    f.write(f"file '{audio_after.replace(chr(92), '/')}'\n")
                    
            merged_audio = os.path.join(temp_dir, "merged.wav")
            run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", merged_audio])
            
            # Mux
            print("[*] 正在混流生成最终视频...")
            run_cmd(["ffmpeg", "-y", "-i", args.target, "-i", merged_audio, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-map", "0:v:0", "-map", "1:a:0", "-shortest", args.out])
            
        else:
            print("[*] 正在将目标视频的整个音频流替换...")
            run_cmd(["ffmpeg", "-y", "-i", args.target, "-i", extracted_audio, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-map", "0:v:0", "-map", "1:a:0", "-shortest", args.out])
            
        print(f"[*] 处理完成！输出文件: {args.out}")
        
        if args.time:
            print(f"[*] 正在修改文件时间...")
            modify_times(args.out, args.time)
            
    except Exception as e:
        print(f"[!] 发生错误: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if len(sys.argv) == 1:
            input("按回车键退出...")

if __name__ == "__main__":
    main()
