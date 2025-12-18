import streamlit as st
from google import genai
import tempfile, os, time, json, asyncio, edge_tts, subprocess, shutil, re, random
from itertools import cycle
from PIL import Image

# --- 깃허브 클라우드 설정 ---
st.set_page_config(page_title="Hybrid Cloud Factory", layout="wide")
st.title("☁️ 깃허브 하이브리드 공장 (모델 자동 전환)")

# API 키
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

def extract_smart_frames(input_path, output_dir, start_sec, duration=60):
    if not os.path.exists(output_dir): os.makedirs(output_dir)
    chunk_folder = os.path.join(output_dir, f"chunk_{start_sec}")
    os.makedirs(chunk_folder, exist_ok=True)
    
    # 깃허브 서버의 힘을 빌려 480p로 적절히 타협 (분석용)
    cmd = [
        ffmpeg_cmd, '-y', '-ss', str(start_sec), '-t', str(duration),
        '-i', input_path,
        '-vf', "select='gt(scene,0.3)',scale=480:-1", 
        '-vsync', 'vfr', '-q:v', '5',
        os.path.join(chunk_folder, "scene_%04d.jpg")
    ]
    subprocess.run(cmd, capture_output=True)
    return [os.path.join(chunk_folder, f) for f in sorted(os.listdir(chunk_folder)) if f.endswith(".jpg")]

# --- [핵심] 하이브리드 생성 함수 ---
def generate_content_safe(client, images, prompt):
    # 1순위: 1.5 Flash (안정적) -> 2순위: 2.0 Flash (최신)
    # 사용자 키가 무엇을 지원하든 둘 중 하나는 무조건 됩니다.
    models = ["gemini-1.5-flash", "gemini-2.0-flash"]
    
    last_error = None
    for model_name in models:
        try:
            # 1.5가 안 되면 catch로 넘어가서 바로 2.0 실행
            response = client.models.generate_content(model=model_name, contents=images + [prompt])
            return response.text
        except Exception as e:
            last_error = e
            if "429" in str(e): # 429(과열)는 모델 문제가 아니므로 잠시 대기
                time.sleep(2)
            continue # 다음 모델 시도
            
    # 모든 모델 실패 시 에러 발생
    raise last_error

# --- 메인 로직 ---
files = st.file_uploader("영상 업로드 (자동 모델 감지)", accept_multiple_files=True)

if files and st.button("🚀 하이브리드 분석 시작"):
    for idx, f in enumerate(files):
        st.divider()
        st.subheader(f"📺 {f.name} 가동 중...")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = os.path.join(tmpdir, f.name)
            with open(original_path, "wb") as tmp_f:
                tmp_f.write(f.read())

            try:
                res = subprocess.run([ffmpeg_cmd, '-i', original_path], stderr=subprocess.PIPE, text=True)
                match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", res.stderr)
                h, m, s = map(int, match.groups())
                total_duration = h*3600 + m*60 + s
            except: total_duration = 3600

            chunk_summaries = []
            for start in range(0, total_duration, 60):
                with st.status(f"☁️ {start//60}분대 분석 중...", expanded=False) as status:
                    frames = extract_smart_frames(original_path, tmpdir, start)
                    if len(frames) > 30: frames = frames[::len(frames)//30]
                    if not frames: continue

                    images = [Image.open(p) for p in frames]
                    
                    success = False
                    while not success:
                        client, _ = get_next_client()
                        try:
                            # [수정됨] 하이브리드 함수 사용
                            text = generate_content_safe(client, images, "이 구간 요약해줘")
                            chunk_summaries.append(text)
                            success = True
                            time.sleep(1)
                        except Exception as e:
                            if "429" in str(e):
                                status.write("속도 조절 중 (5초)...")
                                time.sleep(5)
                            else: 
                                status.write(f"패스 (에러: {e})")
                                break
            
            if chunk_summaries:
                with st.spinner("🎬 최종 영상 제작 중..."):
                    client, _ = get_next_client()
                    final_prompt = f"3개국어(ko,en,es) 대본, 하이라이트, 제목 JSON으로 줘: {' '.join(chunk_summaries)}"
                    
                    # 최종 생성도 하이브리드로 시도
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
                                    subprocess.run([ffmpeg_cmd, '-y', '-ss', str(h['start']), '-t', str(h['end']-h['start']), '-i', original_path, '-vf', 'scale=1920:-1', '-c:v', 'libx264', '-preset', 'ultrafast', c_p], capture_output=True)
                                    subprocess.run([ffmpeg_cmd, '-y', '-i', c_p, '-i', v_p, '-c:v', 'copy', '-c:a', 'aac', '-shortest', out_name], capture_output=True)
                                    with open(out_name, "rb") as f:
                                        st.download_button(f"📥 {l_n} 다운로드", f, file_name=out_name)
                                except: pass
                    else: st.error("최종 생성 실패")
