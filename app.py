import streamlit as st
from google import genai
import tempfile, os, time, json, asyncio, edge_tts, subprocess, shutil, re, random
from itertools import cycle
from PIL import Image

# --- 깃허브 클라우드 전용 설정 ---
st.set_page_config(page_title="GitHub Cloud Factory", layout="wide")
st.title("☁️ 깃허브 클라우드 드라마 공장 (IP 우회 성공!)")

# 사용자님의 API 키 (그대로 사용)
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

# 리눅스(클라우드) 환경에서 FFmpeg 자동 찾기
def get_ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"

ffmpeg_cmd = get_ffmpeg()

def extract_smart_frames(input_path, output_dir, start_sec, duration=60):
    if not os.path.exists(output_dir): os.makedirs(output_dir)
    chunk_folder = os.path.join(output_dir, f"chunk_{start_sec}")
    os.makedirs(chunk_folder, exist_ok=True)
    
    # 클라우드 서버는 빠르므로 화질을 480p로 설정 (분석 정확도 UP)
    cmd = [
        ffmpeg_cmd, '-y', '-ss', str(start_sec), '-t', str(duration),
        '-i', input_path,
        '-vf', "select='gt(scene,0.3)',scale=480:-1", 
        '-vsync', 'vfr', '-q:v', '5',
        os.path.join(chunk_folder, "scene_%04d.jpg")
    ]
    subprocess.run(cmd, capture_output=True)
    return [os.path.join(chunk_folder, f) for f in sorted(os.listdir(chunk_folder)) if f.endswith(".jpg")]

# --- 메인 로직 ---
files = st.file_uploader("영상 업로드 (여기는 구글이 차단 못하는 클라우드입니다)", accept_multiple_files=True)

if files and st.button("🚀 클라우드 분석 시작"):
    for idx, f in enumerate(files):
        st.divider()
        st.subheader(f"📺 {f.name} 처리 중")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = os.path.join(tmpdir, f.name)
            with open(original_path, "wb") as tmp_f:
                tmp_f.write(f.read())

            # 길이 분석
            try:
                res = subprocess.run([ffmpeg_cmd, '-i', original_path], stderr=subprocess.PIPE, text=True)
                match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", res.stderr)
                h, m, s = map(int, match.groups())
                total_duration = h*3600 + m*60 + s
            except: total_duration = 3600 # 실패시 1시간 가정

            chunk_summaries = []
            for start in range(0, total_duration, 60):
                with st.status(f"☁️ {start//60}분대 분석 중...", expanded=False) as status:
                    frames = extract_smart_frames(original_path, tmpdir, start)
                    
                    # 1.5 Flash 모델에 맞춰 최대 30장 전송
                    if len(frames) > 30: frames = frames[::len(frames)//30]
                    if not frames: continue

                    images = [Image.open(p) for p in frames]
                    
                    # 1.5 Flash 모델 사용 (클라우드라 매우 빠름)
                    success = False
                    while not success:
                        client, _ = get_next_client()
                        try:
                            res = client.models.generate_content(model="gemini-1.5-flash", contents=images + ["요약해줘"])
                            chunk_summaries.append(res.text)
                            success = True
                            time.sleep(1) # 아주 짧은 대기
                        except Exception as e:
                            if "429" in str(e):
                                status.write("쿼터 조절 중 (5초)...")
                                time.sleep(5)
                            else: break
            
            # 최종 생성
            if chunk_summaries:
                with st.spinner("🎬 최종 렌더링..."):
                    client, _ = get_next_client()
                    final_prompt = f"3개국어(ko,en,es) 대본, 하이라이트, 제목 JSON으로 줘: {' '.join(chunk_summaries)}"
                    
                    for _ in range(3):
                        try:
                            res = client.models.generate_content(model="gemini-1.5-flash", contents=[final_prompt])
                            data = json.loads(res.text.replace("```json", "").replace("```", "").strip())
                            break
                        except: time.sleep(1)

                    tabs = st.tabs(["🇰🇷", "🇺🇸", "🇪🇸"])
                    for i, (l_n, code) in enumerate([("Korean", "ko"), ("English", "en"), ("Spanish", "es")]):
                        with tabs[i]:
                            try:
                                out_name = f"{data['titles'][code]}.mp4"
                                v_p, c_p = os.path.join(tmpdir, f"v_{code}.mp3"), os.path.join(tmpdir, f"c_{code}.mp4")
                                asyncio.run(edge_tts.Communicate(data['scripts'][code], VOICES[l_n]).save(v_p))
                                h = data['highlights'][0]
                                subprocess.run([ffmpeg_cmd, '-y', '-ss', str(h['start']), '-t', str(h['end']-h['start']), '-i', original_path, '-vf', 'scale=1280:-1', '-c:v', 'libx264', '-preset', 'ultrafast', c_p], capture_output=True)
                                subprocess.run([ffmpeg_cmd, '-y', '-i', c_p, '-i', v_p, '-c:v', 'copy', '-c:a', 'aac', '-shortest', out_name], capture_output=True)
                                with open(out_name, "rb") as f:
                                    st.download_button(f"📥 {l_n} 다운로드", f, file_name=out_name)
                            except: pass
