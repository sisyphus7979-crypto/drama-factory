import streamlit as st
from google import genai
import tempfile, os, time, json, asyncio, edge_tts, subprocess, shutil, re, random
from itertools import cycle
from PIL import Image
import yt_dlp

# --- 통합 공장 설정 ---
st.set_page_config(page_title="Final Drama Factory", layout="wide")
st.title("🏭 깃허브 통합 드라마 공장 (413 에러 해결판)")

API_KEYS = [
    "AIzaSyBV9HQYl_oeQBJVWJ4DAiW0rE5BqLFr15I",
    "AIzaSyDQnDBENF-FiXwXOS36wUyK80UJHKxRyps",
    "AIzaSyCgLWtM2CGJkj7-m62lwbD83XfhUBnaN9k"
]
key_pool = cycle(API_KEYS)
VOICES = {"Korean": "ko-KR-SunHiNeural", "English": "en-US-AndrewNeural", "Spanish": "es-MX-DaliaNeural"}

def get_next_client(): return genai.Client(api_key=next(key_pool)), next(key_pool)
def get_ffmpeg(): return shutil.which("ffmpeg") or "ffmpeg"
ffmpeg_cmd = get_ffmpeg()

# --- 하이브리드 분석 엔진 ---
def generate_content_safe(client, images, prompt):
    models = ["gemini-1.5-flash", "gemini-2.0-flash"]
    for model_name in models:
        try:
            return client.models.generate_content(model=model_name, contents=images + [prompt]).text
        except Exception as e:
            if "429" in str(e): time.sleep(2); continue
            continue
    return ""

def extract_smart_frames(input_path, output_dir, start_sec, duration=60):
    if not os.path.exists(output_dir): os.makedirs(output_dir)
    chunk_folder = os.path.join(output_dir, f"chunk_{start_sec}")
    os.makedirs(chunk_folder, exist_ok=True)
    subprocess.run([ffmpeg_cmd, '-y', '-ss', str(start_sec), '-t', str(duration), '-i', input_path, '-vf', "select='gt(scene,0.3)',scale=480:-1", '-vsync', 'vfr', '-q:v', '5', os.path.join(chunk_folder, "scene_%04d.jpg")], capture_output=True)
    return [os.path.join(chunk_folder, f) for f in sorted(os.listdir(chunk_folder)) if f.endswith(".jpg")]

# --- 메인 로직 ---
tab1, tab2, tab3 = st.tabs(["📂 직접 선택 (413 해결)", "🔗 URL 다운로드", "📤 일반 업로드"])
video_path = None
tmpdir = tempfile.mkdtemp()

with tab1:
    st.info("💡 왼쪽 파일 목록에 드래그&드롭한 영상을 여기서 선택하세요.")
    # 현재 폴더에 있는 영상 파일 자동 감지
    local_files = [f for f in os.listdir('.') if f.endswith(('.mp4', '.mkv', '.avi', '.mov'))]
    selected_file = st.selectbox("분석할 파일 선택", ["선택안함"] + local_files)
    if selected_file != "선택안함":
        video_path = os.path.abspath(selected_file)
        st.success(f"✅ 파일 로드 완료: {selected_file}")

with tab2:
    url = st.text_input("영상 주소 (http://...)")
    if url and st.button("영상 추출하기"):
        with st.spinner("다운로드 중..."):
            ydl_opts = {'outtmpl': os.path.join(tmpdir, 'download.%(ext)s'), 'format': 'best[ext=mp4]'}
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    video_path = ydl.prepare_filename(info)
                    st.success("✅ 다운로드 성공!")
            except Exception as e: st.error(f"실패: {e}")

with tab3:
    up_file = st.file_uploader("작은 파일 업로드 (200MB 이하)", accept_multiple_files=False)
    if up_file:
        video_path = os.path.join(tmpdir, up_file.name)
        with open(video_path, "wb") as f: f.write(up_file.read())
        st.success("✅ 업로드 완료")

if video_path and st.button("🚀 통합 분석 시작"):
    st.divider()
    
    # 영상 길이 확인
    try:
        res = subprocess.run([ffmpeg_cmd, '-i', video_path], stderr=subprocess.PIPE, text=True)
        total_duration = int(float(re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", res.stderr).groups()[0]) * 3600 + float(re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", res.stderr).groups()[1]) * 60 + float(re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", res.stderr).groups()[2]))
    except: total_duration = 3600

    chunk_summaries = []
    for start in range(0, total_duration, 60):
        with st.status(f"☁️ {start//60}분대 정밀 분석...", expanded=False) as status:
            frames = extract_smart_frames(video_path, tmpdir, start)
            if len(frames) > 30: frames = frames[::len(frames)//30]
            if not frames: continue
            
            images = [Image.open(p) for p in frames]
            success = False
            while not success:
                client, _ = get_next_client()
                try:
                    text = generate_content_safe(client, images, "이 구간 요약해줘")
                    if text: chunk_summaries.append(text); success = True
                    else: break
                except: time.sleep(1)
    
    if chunk_summaries:
        with st.spinner("🎬 최종 렌더링..."):
            client, _ = get_next_client()
            final_prompt = f"3개국어(ko,en,es) 대본, 하이라이트, 제목 JSON으로: {' '.join(chunk_summaries)}"
            for _ in range(3):
                try:
                    data = json.loads(generate_content_safe(client, [], final_prompt).replace("```json", "").replace("```", "").strip())
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
                            with open(out_name, "rb") as f: st.download_button(f"📥 {l_n} 다운로드", f, file_name=out_name)
                        except: pass
