import streamlit as st

st.set_page_config(page_title="My Portfolio", layout="wide")

st.title("My Portfolio")
st.write("Welcome! Here's a snapshot of my technical skills and expertise.")

st.divider()

# --- Skills Data ---
skills = {
    "Programming Languages": {
        "Python": 90,
        "JavaScript": 75,
        "SQL": 80,
        "Java": 60,
    },
    "Data & Analytics": {
        "Pandas": 85,
        "NumPy": 80,
        "Data Visualization": 75,
        "Machine Learning": 65,
    },
    "Web Development": {
        "Streamlit": 90,
        "HTML/CSS": 70,
        "React": 55,
        "REST APIs": 80,
    },
    "Tools & Platforms": {
        "Git": 85,
        "Docker": 60,
        "AWS": 50,
        "Linux": 70,
    },
}

# --- Display Skills ---
st.header("Skills")

cols = st.columns(2)

for idx, (category, category_skills) in enumerate(skills.items()):
    with cols[idx % 2]:
        st.subheader(category)
        for skill_name, proficiency in category_skills.items():
            st.write(f"**{skill_name}**")
            st.progress(proficiency / 100, text=f"{proficiency}%")
        st.write("")  # spacing between categories
