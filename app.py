import streamlit as st
from google import genai
import tempfile, os, time, json, asyncio, edge_tts, subprocess, shutil, re, random
from itertools import cycle
from PIL import Image
import yt_dlp # 영상 추출 도구 추가

# --- 설정 ---
st.set_page_config(page_title="Universal Drama Factory", layout="wide")
st.title("☁️ 만능 드라마 공장 (파일 업로드 + URL 추출)")

API_KEYS = [
    "AIzaSyBV9HQYl_oeQBJVWJ4DAiW0rE5BqLFr15I",
    "AIzaSyDQnDBENF-FiXwXOS36wUyK80UJHKxRyps",
    "AIzaSyCgLWtM2CGJkj7-m62lwbD83XfhUBnaN9k"
]
key_pool = cycle(API_KEYS)
VOICES = {"Korean": "ko-KR-SunHiNeural", "English": "en-US-AndrewNeural", "Spanish": "es-MX-DaliaNeural"}

def get_next_client():
    next_key = next(key_pool)
    return genai.Client(api_key=next_key), next_key

def get_ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"

ffmpeg_cmd = get_ffmpeg()

# --- 핵심: URL에서 영상 다운로드 함수 ---
def download_video(url, output_dir):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', # MP4 선호
        'outtmpl': os.path.join(output_dir, 'downloaded_video.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename
        except Exception as e:
            st.error(f"다운로드 실패: {e}")
            return None

# --- 분석 함수들 (기존 동일) ---
def extract_smart_frames(input_path, output_dir, start_sec, duration=60):
    if not os.path.exists(output_dir): os.makedirs(output_dir)
    chunk_folder = os.path.join(output_dir, f"chunk_{start_sec}")
    os.makedirs(chunk_folder, exist_ok=True)
    
    cmd = [
        ffmpeg_cmd, '-y', '-ss', str(start_sec), '-t', str(duration),
        '-i', input_path,
        '-vf', "select='gt(scene,0.3)',scale=480:-1", 
        '-vsync', 'vfr', '-q:v', '5',
        os.path.join(chunk_folder, "scene_%04d.jpg")
    ]
    subprocess.run(cmd, capture_output=True)
    return [os.path.join(chunk_folder, f) for f in sorted(os.listdir(chunk_folder)) if f.endswith(".jpg")]

def generate_content_safe(client, images, prompt):
    models = ["gemini-1.5-flash", "gemini-2.0-flash"]
    for model_name in models:
        try:
            response = client.models.generate_content(model=model_name, contents=images + [prompt])
            return response.text
        except Exception as e:
            if "429" in str(e): time.sleep(2); continue
            continue
    return ""

# --- 메인 로직 ---
tab1, tab2 = st.tabs(["📂 파일 업로드", "🔗 URL 다운로드"])

video_path = None
tmpdir = tempfile.mkdtemp() # 임시 폴더 생성

with tab1:
    files = st.file_uploader("PC에 있는 영상 올리기", accept_multiple_files=False)
    if files:
        video_path = os.path.join(tmpdir, files.name)
        with open(video_path, "wb") as f: f.write(files.read())
        st.success(f"파일 준비 완료: {files.name}")

with tab2:
    url = st.text_input("영상 주소 입력 (http://...)")
    if url and st.button("영상 추출 시도"):
        with st.spinner("사이트에서 영상 추출 중... (시간이 좀 걸립니다)"):
            downloaded = download_video(url, tmpdir)
            if downloaded:
                video_path = downloaded
                st.success(f"추출 성공! 분석 준비 완료.")
            else:
                st.error("이 사이트는 보안이 걸려있어 추출할 수 없습니다.")

# --- 공통 분석 로직 ---
if video_path and st.button("🚀 분석 시작"):
    st.divider()
    st.info("분석 엔진 가동...")
    
    # 길이 분석
    try:
        res = subprocess.run([ffmpeg_cmd, '-i', video_path], stderr=subprocess.PIPE, text=True)
        match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", res.stderr)
        h, m, s = map(int, match.groups())
        total_duration = h*3600 + m*60 + s
    except: total_duration = 3600

    chunk_summaries = []
    for start in range(0, total_duration, 60):
        with st.status(f"☁️ {start//60}분대 분석 중...", expanded=False) as status:
            frames = extract_smart_frames(video_path, tmpdir, start)
            if len(frames) > 30: frames = frames[::len(frames)//30]
            if not frames: continue

            images = [Image.open(p) for p in frames]
            
            success = False
            while not success:
                client, _ = get_next_client()
                try:
                    text = generate_content_safe(client, images, "이 구간 요약해줘")
                    if text:
                        chunk_summaries.append(text)
                        success = True
                    else: break
                except: time.sleep(2)
    
    if chunk_summaries:
        with st.spinner("🎬 최종 영상 제작 중..."):
            client, _ = get_next_client()
            final_prompt = f"3개국어(ko,en,es) 대본, 하이라이트, 제목 JSON으로 줘: {' '.join(chunk_summaries)}"
            
            data = None
            for _ in range(3):
                try:
                    text = generate_content_safe(client, [], final_prompt)
                    data = json.loads(text.replace("```json", "").replace("```", "").strip())
                    break
                except: time.sleep(1)
            
            if data:
                tabs = st.tabs(["🇰🇷", "🇺🇸", "🇪🇸"])
                for i, (l_n, code) in enumerate([("Korean", "ko"), ("English", "en"), ("Spanish", "es")]):
                    with tabs[i]:
                        try:
                            out_name = f"{data['titles'][code]}.mp4"
                            v_p, c_p = os.path.join(tmpdir, f"v_{code}.mp3"), os.path.join(tmpdir, f"c_{code}.mp4")
                            asyncio.run(edge_tts.Communicate(data['scripts'][code], VOICES[l_n]).save(v_p))
                            h = data['highlights'][0]
                            subprocess.run([ffmpeg_cmd, '-y', '-ss', str(h['start']), '-t', str(h['end']-h['start']), '-i', video_path, '-vf', 'scale=1280:-1', '-c:v', 'libx264', '-preset', 'ultrafast', c_p], capture_output=True)
                            subprocess.run([ffmpeg_cmd, '-y', '-i', c_p, '-i', v_p, '-c:v', 'copy', '-c:a', 'aac', '-shortest', out_name], capture_output=True)
                            with open(out_name, "rb") as f:
                                st.download_button(f"📥 {l_n} 다운로드", f, file_name=out_name)
                        except: pass
            else: st.error("최종 생성 실패")
