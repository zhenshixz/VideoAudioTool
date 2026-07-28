
        // Custom Dual Range Slider Class
        class DualSlider {
            constructor(containerId, onUpdate) {
                this.container = document.getElementById(containerId);
                this.track = this.container.querySelector('.dual-slider-track');
                this.range = this.container.querySelector('.dual-slider-range');
                this.thumbLeft = this.container.querySelector('.thumb-left');
                this.thumbRight = this.container.querySelector('.thumb-right');
                
                this.min = 0; this.max = 100;
                this.val1 = 0; this.val2 = 100;
                this.onUpdate = onUpdate;
                this.isDragging = false;
                this.activeThumb = null;

                const startDrag = (e, thumb) => {
                    this.isDragging = true;
                    this.activeThumb = thumb;
                    if (e.cancelable) e.preventDefault();
                };
                
                this.thumbLeft.addEventListener('mousedown', (e) => startDrag(e, 'left'));
                this.thumbRight.addEventListener('mousedown', (e) => startDrag(e, 'right'));
                
                this.thumbLeft.addEventListener('touchstart', (e) => startDrag(e, 'left'), { passive: false });
                this.thumbRight.addEventListener('touchstart', (e) => startDrag(e, 'right'), { passive: false });
                
                const handleMove = (clientX) => {
                    if (!this.isDragging) return;
                    const rect = this.track.getBoundingClientRect();
                    let pos = (clientX - rect.left) / rect.width;
                    pos = Math.max(0, Math.min(1, pos));
                    let val = this.min + pos * (this.max - this.min);
                    
                    if (this.activeThumb === 'left') {
                        this.val1 = Math.min(val, this.val2 - 0.1);
                    } else {
                        this.val2 = Math.max(val, this.val1 + 0.1);
                    }
                    this.updateUI();
                    if (this.onUpdate) this.onUpdate(this.val1, this.val2, this.activeThumb);
                };

                document.addEventListener('mousemove', (e) => handleMove(e.clientX));
                document.addEventListener('touchmove', (e) => {
                    if (!this.isDragging) return;
                    if (e.touches && e.touches.length > 0) {
                        handleMove(e.touches[0].clientX);
                        if (e.cancelable) e.preventDefault();
                    }
                }, { passive: false });
                
                document.addEventListener('mouseup', () => { this.isDragging = false; this.activeThumb = null; });
                document.addEventListener('touchend', () => { this.isDragging = false; this.activeThumb = null; });
                document.addEventListener('touchcancel', () => { this.isDragging = false; this.activeThumb = null; });
            }
            
            init(min, max) {
                this.min = min; this.max = max;
                this.val1 = min; this.val2 = max;
                this.updateUI();
                if (this.onUpdate) this.onUpdate(this.val1, this.val2, null);
            }
            
            updateUI() {
                if (this.max === this.min) return;
                const p1 = ((this.val1 - this.min) / (this.max - this.min)) * 100;
                const p2 = ((this.val2 - this.min) / (this.max - this.min)) * 100;
                this.thumbLeft.style.left = `${p1}%`;
                this.thumbRight.style.left = `${p2}%`;
                this.range.style.left = `${p1}%`;
                this.range.style.width = `${p2 - p1}%`;
            }
        }

        function formatTime(s) {
            const m = Math.floor(s / 60);
            const sec = (s % 60).toFixed(1);
            return `${String(m).padStart(2, '0')}:${String(sec).padStart(4, '0')}`;
        }

        let srcInfo = { duration: 0 };
        let targetInfo = { duration: 0 };
        let mp3ExtractInfo = { duration: 0 };
        let mp3TargetInfo = { duration: 0 };
        
        let srcVals = { start: 0, end: 0 };
        let mp3ExtractVals = { start: 0, end: 0 };
        let targetStartVal = 0;
        let mp3TargetStartVal = 0;

        const srcSlider = new DualSlider('srcSlider', (v1, v2, thumb) => {
            srcVals.start = v1; srcVals.end = v2;
            document.getElementById('srcTimeText').innerText = `${formatTime(v1)} - ${formatTime(v2)} (时长: ${(v2 - v1).toFixed(1)}s)`;
            const video = document.getElementById('srcVideo');
            if (thumb === 'left') video.currentTime = v1;
            else if (thumb === 'right') video.currentTime = v2;
        });

        const mp3ExtractSlider = new DualSlider('mp3ExtractSlider', (v1, v2, thumb) => {
            mp3ExtractVals.start = v1; mp3ExtractVals.end = v2;
            document.getElementById('mp3ExtractTimeText').innerText = `${formatTime(v1)} - ${formatTime(v2)} (时长: ${(v2 - v1).toFixed(1)}s)`;
            const video = document.getElementById('mp3ExtractVideo');
            if (thumb === 'left') video.currentTime = v1;
            else if (thumb === 'right') video.currentTime = v2;
        });

        function onTargetStartChange() {
            const val = parseFloat(document.getElementById('targetStart').value) || 0;
            targetStartVal = val;
            document.getElementById('targetTimeText').innerText = `插入起点: ${formatTime(val)}`;
            const video = document.getElementById('targetVideo');
            video.currentTime = val;
        }

        function onMp3TargetStartChange() {
            const val = parseFloat(document.getElementById('mp3TargetStart').value) || 0;
            mp3TargetStartVal = val;
            document.getElementById('mp3TargetTimeText').innerText = `插入起点: ${formatTime(val)}`;
            const video = document.getElementById('mp3TargetVideo');
            video.currentTime = val;
        }

        function triggerUpload(type) { document.getElementById(type + 'FileInput').click(); }

        async function handleFileUpload(type) {
            const fileInput = document.getElementById(type + 'FileInput');
            if (!fileInput.files.length) return;
            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            showLoading("正在上传视频...");
            try {
                const res = await fetch('/api/upload', { method: 'POST', body: formData });
                const data = await res.json();
                hideLoading();
                if (data.success) {
                    document.getElementById(type + 'Path').value = data.filepath;
                    setVideoSource(type, data.filepath, data.info);
                } else alert("上传失败: " + data.error);
            } catch (err) { hideLoading(); alert("网络错误: " + err.message); }
        }

        async function loadVideoInfo(type) {
            const path = document.getElementById(type + 'Path').value.trim();
            if (!path) return;
            try {
                const res = await fetch('/api/video_info', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filepath: path })
                });
                const data = await res.json();
                if (data.success) setVideoSource(type, path, data.info);
            } catch (err) { console.error(err); }
        }

        function switchTab(tab) {
            document.getElementById('tabAudioBtn').classList.toggle('active', tab === 'audio');
            document.getElementById('tabTimeBtn').classList.toggle('active', tab === 'time');
                        document.getElementById('tabMp3Btn').classList.toggle('active', tab === 'mp3');
            document.getElementById('tabVolumeBtn').classList.toggle('active', tab === 'volume');
            
            document.getElementById('panelAudioTrack').classList.toggle('active', tab === 'audio');
            document.getElementById('panelTimeEdit').classList.toggle('active', tab === 'time');
                        document.getElementById('panelMp3').classList.toggle('active', tab === 'mp3');
            document.getElementById('panelVolume').classList.toggle('active', tab === 'volume');
            
            const exportBtn = document.getElementById('headerExportBtn');
            if (exportBtn) exportBtn.style.display = (tab === 'audio' ? 'inline-flex' : 'none');
            const openBtn = document.getElementById('headerOpenBtn');
            if (openBtn) openBtn.style.display = (tab === 'audio' ? 'inline-flex' : 'none');
        }

        function setVideoSource(type, path, info) {
            const videoEl = document.getElementById(type + 'Video');
            const placeholder = document.getElementById(type + 'Placeholder');
            if (placeholder) placeholder.style.display = 'none';
            if (videoEl) {
                videoEl.src = `/api/stream?path=${encodeURIComponent(path)}`;
                videoEl.style.display = 'block';
            }

            if (type === 'src') {
                srcInfo = info || { duration: videoEl.duration || 0 };
                srcSlider.init(0, srcInfo.duration);
            } else if (type === 'target') {
                targetInfo = info || { duration: videoEl.duration || 0 };
                const dur = targetInfo.duration;
                const startEl = document.getElementById('targetStart');
                startEl.max = dur;
                startEl.value = 0;
                targetStartVal = 0;
                document.getElementById('targetTimeText').innerText = `插入起点: 00:00.0`;
                
                if (info && info.creation_time) document.getElementById('creationTime').value = info.creation_time;
            } else if (type === 'mp3Extract') {
                mp3ExtractInfo = info || { duration: videoEl.duration || 0 };
                mp3ExtractSlider.init(0, mp3ExtractInfo.duration);
            } else if (type === 'mp3Target') {
                mp3TargetInfo = info || { duration: videoEl.duration || 0 };
                const dur = mp3TargetInfo.duration;
                const startEl = document.getElementById('mp3TargetStart');
                startEl.max = dur;
                startEl.value = 0;
                mp3TargetStartVal = 0;
                document.getElementById('mp3TargetTimeText').innerText = `插入起点: 00:00.0`;
            } else if (type === 'volSrc') {
                if (info && info.creation_time) {
                    // do nothing specifically
                }
            } else if (type === 'timeOnly') {
                if (info && info.creation_time) {
                    document.getElementById('timeOnlyVal').value = info.creation_time;
                }
                const infoText = document.getElementById('timeOnlyInfoText');
                if (infoText && info) {
                    infoText.innerText = `视频时长: ${(info.duration || 0).toFixed(1)}s | 原始创建时间: ${info.creation_time || '未知'}`;
                }
            }
        }

        function toggleReplaceMode() {
            const mode = document.getElementById('replaceMode').value;
            if (mode === 'segment') {
                document.getElementById('targetStartBox').style.display = 'block';
            } else {
                document.getElementById('targetStartBox').style.display = 'none';
            }
        }

        function setNowTime() {
            const now = new Date();
            const y = now.getFullYear(); const m = String(now.getMonth()+1).padStart(2,'0'); const d = String(now.getDate()).padStart(2,'0');
            const h = String(now.getHours()).padStart(2,'0'); const min = String(now.getMinutes()).padStart(2,'0'); const s = String(now.getSeconds()).padStart(2,'0');
            document.getElementById('creationTime').value = `${y}-${m}-${d} ${h}:${min}:${s}`;
        }

        function setNowTimeOnly() {
            const now = new Date();
            const y = now.getFullYear(); const m = String(now.getMonth()+1).padStart(2,'0'); const d = String(now.getDate()).padStart(2,'0');
            const h = String(now.getHours()).padStart(2,'0'); const min = String(now.getMinutes()).padStart(2,'0'); const s = String(now.getSeconds()).padStart(2,'0');
            document.getElementById('timeOnlyVal').value = `${y}-${m}-${d} ${h}:${min}:${s}`;
        }

        
        async function isRemote() {
            return window.location.hostname !== '127.0.0.1' && window.location.hostname !== 'localhost';
        }

        async function browseFolderForVol() {
            if (isRemote()) {
                alert("手机端提示：无法调用电脑的文件夹选择器。\n\n请直接留空，处理完成后会自动弹出【下载到手机】的提示。");
                return;
            }
            try {
                const res = await fetch('/api/browse_folder');
                const data = await res.json();
                if (data.success && data.path) {
                    document.getElementById('volOutDir').value = data.path;
                    localStorage.setItem('lastOutDir', data.path);
                }
            } catch (e) {
                console.error("浏览文件夹出错:", e);
            }
        }

        async function browseFolder() {
            if (isRemote()) {
                alert("手机端提示：无法调用电脑的文件夹选择器。\n\n请直接留空，处理完成后会自动弹出【下载到手机】的提示。");
                return;
            }
            try {
                const res = await fetch('/api/browse_folder');
                const data = await res.json();
                if (data.success && data.path) {
                    document.getElementById('outDir').value = data.path;
                }
            } catch (e) {
                console.error("浏览文件夹出错:", e);
            }
        }

        function showExportModal() {
            const srcPath = document.getElementById('srcPath').value.trim();
            const targetPath = document.getElementById('targetPath').value.trim();
            if (!srcPath || !targetPath) {
                alert("请先填写或上传源视频与目标视频！");
                return;
            }
            document.getElementById('exportModalOverlay').style.display = 'flex';
        }

        function hideExportModal() {
            document.getElementById('exportModalOverlay').style.display = 'none';
        }

        async function startExport() {
            hideExportModal();
            const srcPath = document.getElementById('srcPath').value.trim();
            const targetPath = document.getElementById('targetPath').value.trim();

            let outPath = "";
            const outDir = document.getElementById('outDir').value.trim();
            const outFileName = document.getElementById('outFileName').value.trim() || 'edited_video.mp4';
            if (outDir) {
                outPath = outDir + '/' + outFileName;
                localStorage.setItem('lastOutDir', outDir);
            }

            const payload = {
                src_path: srcPath,
                src_start: srcVals.start,
                duration: srcVals.end - srcVals.start,
                target_path: targetPath,
                replace_mode: document.getElementById('replaceMode').value,
                target_start: targetStartVal,
                target_end: -1,
                out_path: outPath,
                creation_time: document.getElementById('creationTime').value.trim()
            };

            showLoading("正在导出并修饰视频时间...");
            try {
                const res = await fetch('/api/process', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                hideLoading();
                if (data.success) {
                    if (confirm(`🎉 导出成功！\n保存文件: ${data.out_path}\n${data.time_modified ? '创建时间已成功更新！' : ''}\n\n是否立即下载该文件到设备？(PC端也可取消后点击📂打开目录)`)) {
                        fetch('/api/open_location', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filepath: data.out_path }) });
                    }
                } else alert("导出失败: " + data.error);
            } catch (err) { hideLoading(); alert("网络错误或系统异常: " + err.message); }
        }

        async function generatePreview() {
            currentPreviewContext = 'audio';
            hideExportModal();
            const srcPath = document.getElementById('srcPath').value.trim();
            const targetPath = document.getElementById('targetPath').value.trim();

            const payload = {
                src_path: srcPath,
                src_start: srcVals.start,
                duration: srcVals.end - srcVals.start,
                target_path: targetPath,
                replace_mode: document.getElementById('replaceMode').value,
                target_start: targetStartVal,
                target_end: -1,
                is_preview: true
            };

            showLoading("正在高速合成预览视频...");
            try {
                const res = await fetch('/api/process', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                hideLoading();
                if (data.success) {
                    const videoEl = document.getElementById('previewVideo');
                    videoEl.src = `/api/stream?path=${encodeURIComponent(data.out_path)}&t=${new Date().getTime()}`;
                    document.getElementById('previewModalOverlay').style.display = 'flex';
                } else {
                    alert("预览生成失败: " + data.error);
                    showExportModal();
                }
            } catch (err) { 
                hideLoading(); 
                alert("网络错误或系统异常: " + err.message); 
                showExportModal();
            }
        }

        
        let currentPreviewContext = 'audio';
        function handlePreviewExport() {
            closePreviewModal();
            if (currentPreviewContext === 'volume') {
                boostVolume(false);
            } else {
                startExport();
            }
        }

        function closePreviewModal() {
            document.getElementById('previewModalOverlay').style.display = 'none';
            const videoEl = document.getElementById('previewVideo');
            videoEl.pause();
            videoEl.src = "";
        }

        async function modifyTimeOnly() {
            const filepath = document.getElementById('timeOnlyPath').value.trim();
            const creation_time = document.getElementById('timeOnlyVal').value.trim();
            const overwrite = document.getElementById('timeOnlyOverwrite').checked;
            
            if (!filepath) { alert("请选择或上传需要修改时间的视频文件！"); return; }
            if (!creation_time) { alert("请填写目标创建时间！"); return; }
            
            showLoading("正在修改视频时间属性...");
            try {
                const res = await fetch('/api/modify_time_only', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filepath, creation_time, overwrite })
                });
                const data = await res.json();
                hideLoading();
                if (data.success) {
                    if (confirm(`✅ 时间修改成功！\n已保存至: ${data.out_path}\n\n是否立即下载该文件到设备？(PC端也可取消后点击📂打开目录)`)) {
                        fetch('/api/open_location', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filepath: data.out_path }) });
                    }
                } else {
                    alert("修改失败: " + data.error);
                }
            } catch (err) { hideLoading(); alert("网络错误或系统异常: " + err.message); }
        }

        
                function onVolDbChange() {
            const val = parseInt(document.getElementById('volDbSlider').value);
            const textEl = document.getElementById('volDbText');
            if (val > 0) {
                textEl.innerText = `+${val} dB (增大)`;
                textEl.style.color = 'var(--danger)';
            } else if (val < 0) {
                textEl.innerText = `${val} dB (减小)`;
                textEl.style.color = 'var(--warning)';
            } else {
                textEl.innerText = `0 dB (原音量)`;
                textEl.style.color = 'var(--primary)';
            }
        }

        async function boostVolume(isPreview = false) {
            const filepath = document.getElementById('volSrcPath').value.trim();
            const volDb = parseFloat(document.getElementById('volDbSlider').value) || 0.0;
            let outPath = "";
            const outDir = document.getElementById('volOutDir').value.trim();
            if (outDir) {
                const filename = filepath.split(/[\\/]/).pop();
                const match = filename.match(/(.*)(\.[^.]+)$/);
                const base = match ? match[1] : filename;
                const ext = match ? match[2] : '';
                outPath = outDir + '/' + base + '_boosted' + ext;
                localStorage.setItem('lastOutDir', outDir);
            }
            
            if (!filepath) { alert("请选择或上传需要扩大音量的视频文件！"); return; }
            
            showLoading(isPreview ? "正在为您生成前10秒的极速预览，请稍候..." : "正在扩大全量视频音量，这可能需要一会儿...");
            try {
                const res = await fetch('/api/boost_volume', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ src_path: filepath, volume_db: volDb, out_path: outPath, is_preview: isPreview })
                });
                const data = await res.json();
                hideLoading();
                if (data.success) {
                    if (isPreview) {
                        currentPreviewContext = 'volume';
                        const videoEl = document.getElementById('previewVideo');
                        videoEl.src = `/api/stream?path=${encodeURIComponent(data.out_path)}&t=${new Date().getTime()}`;
                        document.getElementById('previewModalOverlay').style.display = 'flex';
                    } else {
                        if (confirm(`✅ 扩大音量成功！\n保留了原始创建时间。\n已保存至: ${data.out_path}\n\n是否立即下载该文件到设备？(PC端也可取消后点击📂打开目录)`)) {
                            fetch('/api/open_location', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filepath: data.out_path }) });
                        }
                    }
                } else {
                    alert("处理失败: " + data.error);
                }
            } catch (err) { hideLoading(); alert("网络错误或系统异常: " + err.message); }
        }

        
        function openTargetLocation(moduleId) {
            let path = "";
            if (moduleId === 'time') path = document.getElementById('timeOnlyPath').value.trim();
            else if (moduleId === 'audio') path = document.getElementById('outDir').value.trim() || document.getElementById('targetPath').value.trim();
            else if (moduleId === 'mp3Extract') path = document.getElementById('mp3ExtractPath').value.trim();
            else if (moduleId === 'mp3Target') path = document.getElementById('mp3TargetPath').value.trim();
            else if (moduleId === 'volume') path = document.getElementById('volOutDir').value.trim() || document.getElementById('volSrcPath').value.trim();
            
            if (!path) path = localStorage.getItem('lastOutDir') || "";
            
            if (!path) {
                alert("目前没有可打开的路径，请先上传文件或设置输出目录。");
                return;
            }
            
            fetch('/api/open_location', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filepath: path })
            }).then(res => res.json()).then(data => {
                if (!data.success) alert("打开失败: " + data.error);
            });
        }

        function showLoading(msg) { document.getElementById('loadingText').innerText = msg; document.getElementById('loadingOverlay').style.display = 'flex'; }
        
        async function exportMp3() {
            const srcPath = document.getElementById('mp3ExtractPath').value.trim();
            if (!srcPath) { alert("请先上传待提取音频的源视频！"); return; }
            
            showLoading("正在高速提取 MP3...");
            try {
                const res = await fetch('/api/export_mp3', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        src_path: srcPath,
                        src_start: mp3ExtractVals.start,
                        duration: mp3ExtractVals.end - mp3ExtractVals.start,
                        is_preview: false
                    })
                });
                const data = await res.json();
                hideLoading();
                if (data.success) {
                    if (confirm(`✅ MP3 导出成功！\n已保存至: ${data.out_path}\n\n是否立即下载该文件到设备？(PC端也可取消后点击📂打开目录)`)) {
                        fetch('/api/open_location', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filepath: data.out_path }) });
                    }
                }
                else alert("导出失败: " + data.error);
            } catch (err) { hideLoading(); alert("网络错误: " + err.message); }
        }

        async function previewMp3() {
            const srcPath = document.getElementById('mp3ExtractPath').value.trim();
            if (!srcPath) { alert("请先上传待提取音频的源视频！"); return; }
            
            showLoading("生成 MP3 预览...");
            try {
                const res = await fetch('/api/export_mp3', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        src_path: srcPath,
                        src_start: mp3ExtractVals.start,
                        duration: mp3ExtractVals.end - mp3ExtractVals.start,
                        is_preview: true
                    })
                });
                const data = await res.json();
                hideLoading();
                if (data.success) {
                    const audio = new Audio(`/api/stream?path=${encodeURIComponent(data.out_path)}&t=${new Date().getTime()}`);
                    audio.play();
                    alert("✅ 正在播放预览音频...");
                } else alert("预览生成失败: " + data.error);
            } catch (err) { hideLoading(); alert("网络错误: " + err.message); }
        }

        async function startExportFromMp3() {
            const srcPath = document.getElementById('mp3ImportPath').value.trim();
            const targetPath = document.getElementById('mp3TargetPath').value.trim();
            if (!srcPath || !targetPath) { alert("请先填写 MP3 与目标视频路径！"); return; }
            
            showLoading("正在合并 MP3 与视频...");
            try {
                const res = await fetch('/api/process', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        src_path: srcPath,
                        src_start: 0,
                        duration: 0, 
                        target_path: targetPath,
                        replace_mode: 'segment',
                        target_start: mp3TargetStartVal,
                        is_preview: false
                    })
                });
                const data = await res.json();
                hideLoading();
                if (data.success) alert(`✅ 视频合成成功！\n已保存至: ${data.out_path}`);
                else alert("合成失败: " + data.error);
            } catch (err) { hideLoading(); alert("网络错误: " + err.message); }
        }
        function hideLoading() { document.getElementById('loadingOverlay').style.display = 'none'; }
        
        // Setup initial time and load cache
        window.onload = () => {
            setNowTime();
            setNowTimeOnly();
            const lastOutDir = localStorage.getItem('lastOutDir');
            if (lastOutDir) document.getElementById('outDir').value = lastOutDir;
        };
    
        document.addEventListener('DOMContentLoaded', () => {
            const lastDir = localStorage.getItem('lastOutDir');
            if (lastDir) {
                const dirInputs = ['outDir', 'volOutDir'];
                dirInputs.forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.value = lastDir;
                });
            }
        });

