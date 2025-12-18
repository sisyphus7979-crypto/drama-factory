import streamlit as st
from google import genai
import tempfile, os, time, json, asyncio, edge_tts, subprocess, shutil, re, random
from itertools import cycle
from PIL import Image
import yt_dlp

# --- 설정 ---
st.set_page_config(page_title="Ultimate Factory", layout="wide")
st.title("🏭 최종 완성형 공장 (쿠키 인증 + 속도 최적화)")

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

# --- 디버깅용 하이브리드 엔진 (터미널 로그 출력) ---
def generate_content_safe(client, images, prompt):
    models = ["gemini-1.5-flash", "gemini-2.0-flash"]
    for model_name in models:
        try:
            print(f"   [API] {model_name} 요청...")
            return client.models.generate_content(model=model_name, contents=images + [prompt]).text
        except Exception as e:
            print(f"   [API 에러] {e}")
            if "429" in str(e): time.sleep(2); continue
            continue
    return ""

def extract_smart_frames(input_path, output_dir, start_sec, duration=60):
    if not os.path.exists(output_dir): os.makedirs(output_dir)
    chunk_folder = os.path.join(output_dir, f"chunk_{start_sec}")
    os.makedirs(chunk_folder, exist_ok=True)
    # [속도 최적화] 리사이징 먼저 수행
    subprocess.run([ffmpeg_cmd, '-y', '-ss', str(start_sec), '-t', str(duration), '-i', input_path, '-vf', "scale=320:-1,select='gt(scene,0.3)'", '-vsync', 'vfr', '-q:v', '5', os.path.join(chunk_folder, "scene_%04d.jpg")], capture_output=True)
    return [os.path.join(chunk_folder, f) for f in sorted(os.listdir(chunk_folder)) if f.endswith(".jpg")]

# --- 메인 로직 ---
tab_cookie, tab_file = st.tabs(["🍪 쿠키로 다운로드", "📂 파일 선택 (Resume)"])
video_path = None
progress_dir = "analysis_progress"
if not os.path.exists(progress_dir): os.makedirs(progress_dir)

# 1. 쿠키 다운로드 기능 (다시 추가됨)
with tab_cookie:
    st.info("💡 FetchV m3u8 주소와 'Get cookies.txt' 파일이 필요합니다.")
    col1, col2 = st.columns([1, 2])
    with col1:
        cookie_file = st.file_uploader("쿠키 파일 (.txt)", type=["txt"])
    with col2:
        target_url = st.text_input("m3u8 주소", placeholder="https://...")
        referer_url = st.text_input("원본 사이트 주소 (Referer)", placeholder="https://bbtv86.com/...")

    if target_url and st.button("📥 쿠키 인증 다운로드"):
        cookie_path = None
        if cookie_file:
            cookie_path = os.path.join(tempfile.gettempdir(), "cookies.txt")
            with open(cookie_path, "wb") as f: f.write(cookie_file.read())

        with st.spinner("🍪 신분증(쿠키) 제출 및 다운로드 중..."):
            ydl_opts = {
                'outtmpl': os.path.join(tempfile.gettempdir(), 'download.%(ext)s'),
                'format': 'best',
                'noplaylist': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': referer_url if referer_url else target_url
                }
            }
            if cookie_path: ydl_opts['cookiefile'] = cookie_path

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(target_url, download=True)
                    st.session_state['video_path'] = ydl.prepare_filename(info)
                    st.success("✅ 인증 성공! 다운로드 완료.")
            except Exception as e: st.error(f"❌ 실패: {e}")

# 2. 파일 선택 기능
with tab_file:
    local_files = [f for f in os.listdir('.') if f.endswith(('.mp4', '.mkv', '.avi', '.mov'))]
    selected_local = st.selectbox("분석할 파일 선택", ["선택안함"] + local_files)
    if selected_local != "선택안함":
        video_path = os.path.abspath(selected_local)

# --- 공통 분석 로직 (렉 방지 버전) ---
if st.session_state.get('video_path') or video_path:
    final_path = st.session_state.get('video_path') or video_path
    
    if st.button("🚀 분석 시작 (안정화 모드)"):
        st.divider()
        file_id = re.sub(r'\W+', '_', os.path.basename(final_path))
        save_path = os.path.join(progress_dir, file_id)
        if not os.path.exists(save_path): os.makedirs(save_path)

        try:
            res = subprocess.run([ffmpeg_cmd, '-i', final_path], stderr=subprocess.PIPE, text=True)
            total_duration = int(float(re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", res.stderr).groups()[0]) * 3600 + float(re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", res.stderr).groups()[1]) * 60 + float(re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", res.stderr).groups()[2]))
        except: total_duration = 3600

        chunk_summaries = []
        status_text = st.empty() # 상태창 하나만 사용 (렉 방지)
        p_bar = st.progress(0)
        
        print(f"=== 분석 시작: {os.path.basename(final_path)} ===")

        for start in range(0, total_duration, 60):
            p_bar.progress(min(start / total_duration, 1.0))
            status_text.markdown(f"### ⚡ **{start//60}분대** 처리 중... (터미널 로그 확인)")
            
            save_file = os.path.join(save_path, f"{start}.txt")
            if os.path.exists(save_file):
                with open(save_file, "r", encoding="utf-8") as f: chunk_summaries.append(f.read())
                print(f"   -> {start//60}분: 스킵 (완료됨)")
                continue

            frames = extract_smart_frames(final_path, save_path, start)
            if len(frames) > 30: frames = frames[::len(frames)//30]
            
            if not frames:
                with open(save_file, "w", encoding="utf-8") as f: f.write("")
                continue
            
            images = [Image.open(p) for p in frames]
            success = False
            retry = 0
            while not success and retry < 5:
                client, _ = get_next_client()
                try:
                    text = generate_content_safe(client, images, "이 구간 핵심 요약해줘")
                    if text: 
                        chunk_summaries.append(text)
                        with open(save_file, "w", encoding="utf-8") as f: f.write(text)
                        success = True
                    else: retry += 1
                except: time.sleep(1); retry += 1
        
        p_bar.progress(100)
        status_text.success("🎉 분석 완료!")
        
        if chunk_summaries:
            with st.spinner("🎬 최종 결과물 생성 중..."):
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
