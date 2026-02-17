import streamlit as st
import random
import google.generativeai as genai
from difflib import SequenceMatcher
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# ---------------------------------------------------------
# 1. 설정 & 스타일
# ---------------------------------------------------------
st.set_page_config(page_title="Moonie's English Class", page_icon="🎓")

# [수정됨] 탐지견(Debug 메시지) 철수! 조용히 키만 가져옵니다.
try:
    GENAI_KEY = st.secrets["gemini_api_key"]
    GCP_CREDS = st.secrets["gcp_service_account"]
except:
    st.error("🚨 .streamlit/secrets.toml 파일 설정을 확인해주세요.")
    st.stop()

MODEL_NAME = 'gemini-2.5-flash' 
SHEET_NAME = "Moonie_EnglishBasic_DB" # 구글 시트 이름

st.markdown("""
<style>
    div.stButton > button[kind="primary"],
    div[data-testid="stFormSubmitButton"] > button {
        background-color: #28a745 !important;
        border-color: #28a745 !important;
        color: white !important;
    }
    div[data-baseweb="input"]:focus-within {
        border-color: #28a745 !important;
        box-shadow: 0 0 0 1px #28a745 !important;
    }
    input.stTextInput {
        caret-color: #28a745;
    }
    strong {
        font-weight: 900 !important;
        color: #000000 !important;
    }
    .streamlit-expanderHeader {
        font-size: 0.9em;
        color: #444;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. 구글 시트 연결 함수
# ---------------------------------------------------------
@st.cache_resource
def get_google_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(GCP_CREDS), scope)
    client = gspread.authorize(creds)
    return client

def get_data_from_sheet(worksheet_name):
    try:
        client = get_google_sheet_client()
        sheet = client.open(SHEET_NAME)
        ws = sheet.worksheet(worksheet_name)
        return ws.get_all_records()
    except Exception:
        return []

def add_to_sheet(worksheet_name, q_data):
    try:
        client = get_google_sheet_client()
        sheet = client.open(SHEET_NAME)
        ws = sheet.worksheet(worksheet_name)
        existing = ws.get_all_records()
        if not any(r['key'] == q_data['key'] and r['eng'] == q_data['eng'] for r in existing):
            row = [q_data.get('major'), q_data.get('middle'), q_data.get('minor'), q_data.get('eng'), q_data.get('kor'), q_data.get('key')]
            ws.append_row(row)
    except Exception as e:
        st.error(f"저장 실패: {e}")

def remove_from_sheet(worksheet_name, q_data):
    try:
        client = get_google_sheet_client()
        sheet = client.open(SHEET_NAME)
        ws = sheet.worksheet(worksheet_name)
        records = ws.get_all_records()
        for i, r in enumerate(records):
            if r['key'] == q_data['key'] and r['eng'] == q_data['eng']:
                ws.delete_rows(i + 2)
                break
    except Exception as e:
        st.error(f"삭제 실패: {e}")

def load_incorrect_notes(): return get_data_from_sheet("incorrect")
def load_mastered_notes(): return get_data_from_sheet("mastered")

def add_to_incorrect(q_data): add_to_sheet("incorrect", q_data)
def remove_from_incorrect(q_data): remove_from_sheet("incorrect", q_data)
def add_to_mastered(q_data):
    add_to_sheet("mastered", q_data)
    remove_from_sheet("incorrect", q_data)

def load_quiz_data():
    questions = []
    descriptions = {}
    curr_major = "기타"; curr_middle = "기타"; curr_minor = "전체"; current_key = "기타-기타-전체"
    try:
        with open("quiz_data.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line: continue 
            if line.startswith("[") and line.endswith("]"):
                parts = line[1:-1].split(">")
                curr_major = parts[0].strip()
                curr_middle = parts[1].strip() if len(parts) > 1 else "전체"
                curr_minor = parts[2].strip() if len(parts) > 2 else "전체"
                current_key = f"{curr_major}-{curr_middle}-{curr_minor}"
            elif line.startswith("#"):
                desc_text = line[1:].strip()
                if current_key in descriptions: descriptions[current_key] += f"\n\n{desc_text}"
                else: descriptions[current_key] = desc_text
            elif "|" in line:
                eng, kor = line.split("|")
                questions.append({'major': curr_major, 'middle': curr_middle, 'minor': curr_minor, 'eng': eng.strip(), 'kor': kor.strip(), 'key': current_key})
    except FileNotFoundError:
        st.error("🚨 'quiz_data.txt' 파일이 없습니다."); return [], {}
    return questions, descriptions

ALL_QUESTIONS, ALL_DESCRIPTIONS = load_quiz_data()

# ---------------------------------------------------------
# 3. 채점 함수
# ---------------------------------------------------------
def check_similarity_simple(user, correct):
    u = user.replace(" ", "").replace(".", "").replace(",", "").replace("?", "").replace("!", "").lower()
    c = correct.replace(" ", "").replace(".", "").replace(",", "").replace("?", "").replace("!", "").lower()
    return SequenceMatcher(None, u, c).ratio()

def check_with_ai(user_answer, correct_answer, original_kor):
    try:
        genai.configure(api_key=GENAI_KEY)
        model = genai.GenerativeModel(MODEL_NAME)
        prompt = f"""
        Act as a strict English grammar teacher.
        Check if the Student's English composition is grammatically correct and matches the meaning of the Korean Source.
        
        Korean Source: "{original_kor}"
        Correct Answer (Model): "{correct_answer}"
        Student Answer: "{user_answer}"
        
        Grading Rules:
        1. **Ignore Case & Punctuation**: Treat 'The' and 'the' as same. Ignore missing periods.
        2. **Strict Grammar**: Reject verb tense errors.
        3. **Strict Spelling**: Reject typos.
        4. **Accept Valid Synonyms**: Accept only if grammar is perfect.
        
        Answer only "O" (Correct) or "X" (Incorrect).
        """
        response = model.generate_content(prompt)
        text = response.text.strip().upper()
        if "O" in text: return True
        if "X" in text: return False
        return False
    except: return None

# ---------------------------------------------------------
# 4. 문제 관리 (입력창 포커스 & 상태 관리)
# ---------------------------------------------------------
if 'quiz_step' not in st.session_state: st.session_state.quiz_step = 'answering'
if "quiz_input" not in st.session_state: st.session_state["quiz_input"] = ""

def next_question():
    pool = st.session_state.current_pool
    if not pool: return
    if 'q_index' not in st.session_state: st.session_state.q_index = 0
    
    current_idx = st.session_state.q_index % len(pool)
    q = pool[current_idx]
    st.session_state.quiz_data = q
    
    st.session_state.quiz_step = 'answering'
    st.session_state["quiz_input"] = "" 
    if 'last_wrong_input' in st.session_state: del st.session_state['last_wrong_input']
    st.session_state.q_index += 1

def process_submit():
    q_data = st.session_state.get('quiz_data')
    ans_text = q_data['eng']
    q_text = q_data['kor']
    user_input = st.session_state["quiz_input"]

    if st.session_state.quiz_step == 'answering':
        if not user_input.strip():
             st.session_state.quiz_step = 'correction'
             add_to_incorrect(q_data)
             st.session_state["quiz_input"] = "" 
             st.toast("빈칸입니다! 정답을 따라 써보세요. ✍️")
        else:
            ai_result = check_with_ai(user_input, ans_text, q_text)
            simple_score = check_similarity_simple(user_input, ans_text) * 100
            
            is_correct = False
            if ai_result is True: is_correct = True
            elif ai_result is False: is_correct = False
            else:
                if simple_score >= 95: is_correct = True
                else: is_correct = False
            
            if is_correct:
                st.session_state.quiz_step = 'completed'
                if st.session_state.get('mode_selection') == "🔥 오답 노트": 
                    remove_from_incorrect(q_data); st.toast("오답 삭제됨! 🎓")
            else:
                st.session_state.quiz_step = 'correction'
                st.session_state.last_wrong_input = user_input
                add_to_incorrect(q_data)
                st.session_state["quiz_input"] = "" 
                st.toast("틀렸습니다! 정답을 따라 써서 익혀보세요. ✍️")

    elif st.session_state.quiz_step == 'correction':
        sim = check_similarity_simple(user_input, ans_text)
        if sim >= 0.98:
            st.toast("잘했습니다! 다음 문제로 넘어갑니다. 👏")
            next_question()
        else:
            st.toast("아직 다릅니다. 정답을 똑같이 입력해주세요! 🔥")

    elif st.session_state.quiz_step == 'completed':
        next_question()

def process_graduate():
    q_data = st.session_state.get('quiz_data')
    if q_data:
        add_to_mastered(q_data)
        st.toast("졸업 완료! 👋")
        next_question()

# ---------------------------------------------------------
# 5. 사이드바 (필터링 로직 강화 버전)
# ---------------------------------------------------------
st.title("🎓 Moonie's English Class")
if not ALL_QUESTIONS: st.warning("데이터가 없습니다."); st.stop()

# 시트 데이터 로드
incorrect_list = load_incorrect_notes()
mastered_list = load_mastered_notes()

with st.sidebar:
    st.header("📚 학습 모드 설정")
    mode_selection = st.radio("모드 선택", ["일반 학습", "🔥 오답 노트"])
    st.session_state.mode_selection = mode_selection
    
    # 체크박스: 졸업 문장 포함 여부
    show_mastered = st.checkbox(f"🎓 졸업한 문장 포함 ({len(mastered_list)}개)", value=False)
    st.divider()

    if mode_selection == "🔥 오답 노트":
        if not incorrect_list:
            st.success("🎉 오답 노트가 비어있습니다!")
            st.session_state.current_pool = []
        else:
            st.info(f"오답 {len(incorrect_list)}개 복습 중")
            st.session_state.current_pool = incorrect_list
            if st.session_state.get('last_mode') != 'incorrect':
                st.session_state.last_mode = 'incorrect'
                st.session_state.q_index = 0
                next_question()
                st.rerun()
    else:
        # 드롭다운 메뉴 생성
        all_majors = sorted(list(set(q['major'] for q in ALL_QUESTIONS)))
        sel_major = st.selectbox("1. 대단원", ["전체"] + all_majors, key="major_select")
        
        if sel_major == "전체": middle_opts = sorted(list(set(q['middle'] for q in ALL_QUESTIONS)))
        else: middle_opts = sorted(list(set(q['middle'] for q in ALL_QUESTIONS if q['major'] == sel_major)))
        sel_middle = st.selectbox("2. 중단원", ["전체"] + middle_opts, key=f"mid_{sel_major}")

        if sel_major == "전체": minor_opts = sorted(list(set(q['minor'] for q in ALL_QUESTIONS)))
        elif sel_middle == "전체": minor_opts = sorted(list(set(q['minor'] for q in ALL_QUESTIONS if q['major'] == sel_major)))
        else: minor_opts = sorted(list(set(q['minor'] for q in ALL_QUESTIONS if q['major'] == sel_major and q['middle'] == sel_middle)))
        sel_minor = st.selectbox("3. 소단원", ["전체"] + minor_opts, key=f"min_{sel_major}_{sel_middle}")

        # [핵심 수정] 졸업 데이터 비교 로직 강화 (공백 제거 & 문자열 변환)
        mastered_signatures = set()
        for m in mastered_list:
            # 안전하게 문자열로 바꾸고(str), 앞뒤 공백 제거(strip)
            # key와 영어문장(eng) 두 가지를 합쳐서 '고유 지문'을 만듭니다.
            k = str(m.get('key', '')).strip()
            e = str(m.get('eng', '')).strip()
            if k and e: # 데이터가 비어있지 않을 때만 등록
                mastered_signatures.add((k, e))

        filtered = []
        for q in ALL_QUESTIONS:
            # 1. 사용자가 선택한 단원 필터링
            if sel_major!="전체" and q['major']!=sel_major: continue
            if sel_middle!="전체" and q['middle']!=sel_middle: continue
            if sel_minor!="전체" and q['minor']!=sel_minor: continue
            
            # 2. 졸업 여부 필터링 (똑같이 공백 제거 후 비교)
            q_key = str(q['key']).strip()
            q_eng = str(q['eng']).strip()
            
            # 졸업 목록에 있고, '졸업 문장 포함' 체크가 해제되어 있다면 -> 건너뛰기(continue)
            if not show_mastered and (q_key, q_eng) in mastered_signatures: 
                continue
                
            filtered.append(q)
        
        st.session_state.current_pool = filtered
        st.caption(f"학습할 문제: {len(filtered)}개")
        
        filter_key = f"{sel_major}-{sel_middle}-{sel_minor}-{show_mastered}"
        # 필터가 바뀌면 문제 초기화
        if st.session_state.get('last_filter') != filter_key or st.session_state.get('last_mode') == 'incorrect':
            st.session_state.last_filter = filter_key
            st.session_state.last_mode = 'normal'
            st.session_state.q_index = 0
            next_question()
            st.rerun()

# ---------------------------------------------------------
# 6. 메인 화면
# ---------------------------------------------------------
if 'quiz_data' not in st.session_state: st.session_state.q_index = 0; next_question()
q_data = st.session_state.get('quiz_data')

if not st.session_state.current_pool:
    if mode_selection == "🔥 오답 노트": st.balloons(); st.success("👏 오답 노트 클리어!")
    else: st.warning("문제가 없습니다.")
    st.stop()

q_text = q_data['kor']; ans_text = q_data['eng']; current_selection_key = q_data['key']

st.markdown("---")
st.markdown(f"### {q_text}")

with st.form(key='quiz_form'):
    if st.session_state.quiz_step == 'answering':
        placeholder_text = "영어로 작문하세요"
        btn_label = "정답 확인 (Enter) ✅"
    elif st.session_state.quiz_step == 'correction':
        placeholder_text = "위의 정답을 똑같이 입력하세요"
        btn_label = "확인 (Enter) 🔄"
    else: 
        placeholder_text = "정답입니다. Enter를 누르면 다음 문제로 갑니다."
        btn_label = "다음 문제 (Enter) ➡️"

    st.text_input("입력", label_visibility="collapsed", key="quiz_input", placeholder=placeholder_text)
    st.form_submit_button(btn_label, on_click=process_submit, type="primary", use_container_width=True)

if st.session_state.quiz_step == 'correction':
    st.error(f"내가 쓴 답: {st.session_state.get('last_wrong_input', '(빈칸)')}")
    with st.container(border=True): st.markdown(f"**정답:** :blue[{ans_text}]")
    st.info("👆 위의 정답을 똑같이 입력해야 넘어갈 수 있습니다!")

elif st.session_state.quiz_step == 'completed':
    with st.container(border=True): st.markdown(f"**정답:** :blue[{ans_text}]")
    if mode_selection != "🔥 오답 노트":
        st.button("이 문장 졸업 🎓", on_click=process_graduate, use_container_width=True)

st.markdown("---") 
with st.container(border=True):
    if mode_selection == "🔥 오답 노트": st.caption("🔥 오답 복습 중")
    else: st.caption(f"📂 {q_data['major']} > {q_data['middle']} > {q_data['minor']}")
    if current_selection_key in ALL_DESCRIPTIONS:
        with st.expander("💡 학습 포인트 보기 (Click)", expanded=True): st.markdown(ALL_DESCRIPTIONS[current_selection_key], unsafe_allow_html=True)
    else: st.caption("(이 단원에는 등록된 학습 포인트가 없습니다.)")