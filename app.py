import streamlit as st
from google import genai
import tempfile, os, time, json, asyncio, edge_tts, subprocess, shutil, re, random
from itertools import cycle
from PIL import Image
import yt_dlp

# --- 설정 ---
st.set_page_config(page_title="FetchV Style Factory", layout="wide")
st.title("🏭 FetchV 스타일 드라마 공장")

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

# --- 하이브리드 엔진 ---
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
    subprocess.run([ffmpeg_cmd, '-y', '-ss', str(start_sec), '-t', str(duration), '-i', input_path, '-vf', "scale=320:-1,select='gt(scene,0.3)'", '-vsync', 'vfr', '-q:v', '5', os.path.join(chunk_folder, "scene_%04d.jpg")], capture_output=True)
    return [os.path.join(chunk_folder, f) for f in sorted(os.listdir(chunk_folder)) if f.endswith(".jpg")]

# --- 메인 로직 ---
tab_url, tab_file = st.tabs(["🔗 URL (m3u8 지원)", "📂 파일 선택"])
video_path = None
progress_dir = "analysis_progress"
if not os.path.exists(progress_dir): os.makedirs(progress_dir)

# [핵심 변경] FetchV 처럼 브라우저 위장 다운로드
with tab_url:
    st.info("💡 팁: 일반 주소가 안 되면, FetchV에 뜨는 '.m3u8' 주소를 복사해서 넣어보세요.")
    url_input = st.text_input("영상 주소 (또는 m3u8 주소)", key="url_input")
    
    if url_input and st.button("📥 브라우저 모드로 추출"):
        with st.spinner("브라우저인 척 위장하여 접근 중..."):
            # FetchV 방식: 헤더를 조작하여 차단 우회
            ydl_opts = {
                'outtmpl': os.path.join(tempfile.gettempdir(), 'download.%(ext)s'),
                'format': 'best',
                'noplaylist': True,
                # [중요] 봇 탐지 회피용 헤더 설정
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': url_input,
                    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
                }
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url_input, download=True)
                    st.session_state['video_path'] = ydl.prepare_filename(info)
                    st.success("✅ 추출 성공! (보안 뚫음)")
            except Exception as e: 
                st.error(f"❌ 실패: {e}")
                st.warning("이 사이트는 'm3u8(스트리밍 주소)'를 직접 넣어야 할 수 있습니다.")

with tab_file:
    local_files = [f for f in os.listdir('.') if f.endswith(('.mp4', '.mkv', '.avi', '.mov'))]
    selected_local = st.selectbox("분석할 파일 선택", ["선택안함"] + local_files)
    if selected_local != "선택안함":
        video_path = os.path.abspath(selected_local)

# --- 분석 시작 로직 (Resume 기능 포함) ---
if st.session_state.get('video_path') or video_path:
    final_path = st.session_state.get('video_path') or video_path
    st.divider()
    st.write(f"🎬 분석 대상: `{os.path.basename(final_path)}`")
    
    if st.button("🚀 분석 시작"):
        file_id = re.sub(r'\W+', '_', os.path.basename(final_path))
        save_path = os.path.join(progress_dir, file_id)
        if not os.path.exists(save_path): os.makedirs(save_path)

        # 길이 분석
        try:
            res = subprocess.run([ffmpeg_cmd, '-i', final_path], stderr=subprocess.PIPE, text=True)
            total_duration = int(float(re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", res.stderr).groups()[0]) * 3600 + float(re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", res.stderr).groups()[1]) * 60 + float(re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", res.stderr).groups()[2]))
        except: total_duration = 3600

        chunk_summaries = []
        p_bar = st.progress(0)
        
        for start in range(0, total_duration, 60):
            p_bar.progress(min(start / total_duration, 1.0))
            save_file = os.path.join(save_path, f"{start}.txt")
            
            if os.path.exists(save_file):
                with open(save_file, "r", encoding="utf-8") as f: chunk_summaries.append(f.read())
                continue

            with st.status(f"⚡ {start//60}분대 분석 중...", expanded=False) as status:
                frames = extract_smart_frames(final_path, save_path, start)
                if len(frames) > 30: frames = frames[::len(frames)//30]
                
                if not frames:
                    with open(save_file, "w", encoding="utf-8") as f: f.write("")
                    continue
                
                images = [Image.open(p) for p in frames]
                success = False
                while not success:
                    client, _ = get_next_client()
                    try:
                        text = generate_content_safe(client, images, "이 구간 핵심 요약해줘")
                        if text: 
                            chunk_summaries.append(text)
                            with open(save_file, "w", encoding="utf-8") as f: f.write(text)
                            success = True
                        else: break
                    except: time.sleep(1)
        
        p_bar.progress(100)
        if chunk_summaries:
            with st.spinner("🎬 결과물 생성 중..."):
                client, _ = get_next_client()
                full = ' '.join([c for c in chunk_summaries if c])
                final_prompt = f"3개국어(ko,en,es) 대본, 하이라이트, 제목 JSON으로: {full}"
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
                                v_p, c_p = os.path.join(save_path, f"v_{code}.mp3"), os.path.join(save_path, f"c_{code}.mp4")
                                asyncio.run(edge_tts.Communicate(data['scripts'][code], VOICES[l_n]).save(v_p))
                                h = data['highlights'][0]
                                subprocess.run([ffmpeg_cmd, '-y', '-ss', str(h['start']), '-t', str(h['end']-h['start']), '-i', final_path, '-vf', 'scale=1280:-1', '-c:v', 'libx264', '-preset', 'ultrafast', c_p], capture_output=True)
                                subprocess.run([ffmpeg_cmd, '-y', '-i', c_p, '-i', v_p, '-c:v', 'copy', '-c:a', 'aac', '-shortest', out_name], capture_output=True)
                                with open(out_name, "rb") as f: st.download_button(f"📥 {l_n} 다운로드", f, file_name=out_name)
                            except: pass
