import streamlit as st
import pypdfium2 as pdfium
import os
import textwrap
from collections import deque
from snowflake.core import Root
from snowflake.cortex import Complete
from snowflake.snowpark.context import get_active_session

st.set_page_config(layout="wide")

MODELS = [
    "mistral-large",
    "snowflake-arctic",
    "llama3-70b",
    "llama3-8b",
]

ALL_QUERIES = [
    "What is the Snowflake Arctic Cookbook Series about?",
    "What is Snowflake's Arctic-Embed model?",
    "What are key features of Snowflake's Arctic-TILT model?",
    "How did Snowflake collaborate with the University of Waterloo?",
    "Why use Snowflake's PostgreSQL and MySQL connectors?",
    "How does the Snowflake platform support fine-tuning Llama 3.1?",
    "How does Snowflake's time-series forecasting differ from traditional methods?",
    "How does Snowflake's document intelligence optimize performance?",
    "How does Snowflake aim to improve real-world retrieval applications?",
    "What specific use cases does Snowflake highlight for RAG systems?",
    "How does Snowflake's new AI stack support fine-tuning large models?",
    "What are practical applications of Snowflake's document intelligence?",
    "How does elastic computing support Snowflake's AI research and development?"
]

def init_session_state():
    defaults = {
        'model_name': MODELS[0],
        'num_retrieved_chunks': 5,
        'num_chat_messages': 5,
        'clear_conversation': False,
        'use_chat_history': True,
        'generated_response': "",
        'results': [],
        'pdf_filename': None,
        'selected_pdf_from_results': None,
        'user_question': "",
        'selected_question_key': 0,
        'question_key': 0,
        'messages': deque(maxlen=5)  # Keep a limited chat history
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def init_service_metadata(session):
    if "service_metadata" not in st.session_state:
        services = session.sql("SHOW CORTEX SEARCH SERVICES;").collect()
        service_metadata = []
        default_service_name = "TEXT_SEARCH_SERVICE"
        if services:
            for s in services:
                svc_name = s["name"]
                svc_search_col = session.sql(
                    f"DESC CORTEX SEARCH SERVICE {svc_name};"
                ).collect()[0]["search_column"]
                service_metadata.append(
                    {"name": svc_name, "search_column": svc_search_col}
                )

        st.session_state.service_metadata = service_metadata
        available_services = [s["name"] for s in service_metadata]
        st.session_state.selected_cortex_search_service = (
            default_service_name if default_service_name in available_services else available_services[0]
        )

def init_config_options():
    st.sidebar.selectbox(
        "Select Cortex Search Service:",
        [s["name"] for s in st.session_state.service_metadata],
        key="selected_cortex_search_service",
    )

    clear_button_clicked = st.sidebar.button("Clear conversation")
    if clear_button_clicked:
        st.session_state.clear_conversation = True
        init_session_state()

    use_chat_history = st.sidebar.checkbox(
        "Use chat history", value=st.session_state.use_chat_history
    )
    st.session_state.use_chat_history = use_chat_history

    with st.sidebar.expander("Advanced options"):
        st.selectbox("Select model:", MODELS, key="model_name")
        st.number_input(
            "Select number of context chunks",
            key="num_retrieved_chunks",
            min_value=1,
            max_value=10,
        )
        st.number_input(
            "Select number of messages to use in chat history",
            key="num_chat_messages",
            min_value=1,
            max_value=10,
        )

def query_cortex_search_service(session, query, columns=[], filter={}):
    cortex_search_service = (
        root.databases[session.get_current_database()]
        .schemas[session.get_current_schema()]
        .cortex_search_services[st.session_state.selected_cortex_search_service]
    )

    context_documents = cortex_search_service.search(
        query, columns=columns, filter=filter, limit=st.session_state.num_retrieved_chunks
    )
    results = context_documents.results

    service_metadata = st.session_state.service_metadata
    search_col = [s["search_column"] for s in service_metadata
                  if s["name"] == st.session_state.selected_cortex_search_service][0].lower()

    context_str = ""
    unique_titles = set()

    for i, r in enumerate(results):
        title = r['relative_path']
        if title not in unique_titles:
            unique_titles.add(title)
            context_str += f"Context document {i + 1}: {r[search_col]} \n" + "\n"

    return context_str, results

@st.cache_data
def complete(model, prompt):
    if st.session_state.get("use_customized_qa_model", False):
        model = "customized_QA_model"
    return Complete(model, prompt).replace("$", "\$")

def generate_prompt(user_question, selected_chunks, max_context_length=3000):
    if not selected_chunks:
        return None

    context_str = ""
    current_length = 0

    for chunk in selected_chunks:
        chunk_length = len(chunk['chunk'])
        if current_length + chunk_length <= max_context_length:
            context_str += chunk['chunk'] + " "
            current_length += chunk_length
        else:
            break

    context_str = context_str.strip()[:max_context_length]

    prompt = f"""
    [INST]
    You are a helpful AI assistant specialized in retrieving information from documents. 
    The user has asked the following question:

    <question>
    {user_question}
    </question>

    Based on the context provided, generate a coherent and relevant answer to the question.

    <context>
    {context_str}
    </context>
    [/INST]

    Answer:
    """
    return prompt

def display_pdf(pdf_filename):
    st.write(f"@TALK_TO_DOC.PUBLIC.PDFDOCS/{pdf_filename}")
    session.file.get(f"@TALK_TO_DOC.PUBLIC.PDFDOCS/{pdf_filename}", "/tmp/pdf")
    pdf = pdfium.PdfDocument(f"/tmp/{pdf_filename}")
    page = pdf[0]  # Load the first page
    bitmap = page.render(scale=1, rotation=0)
    pil_image = bitmap.to_pil()
    st.image(pil_image)

def save_to_snowflake(session, table_name, question, answer, file_url, chunk, language, meta_info, relative_path):
    session.sql(f"""CREATE TABLE IF NOT EXISTS {table_name} (
            RAGQuestion STRING,
            RAGAnswer STRING,
            file_url STRING,
            chunk STRING,
            language STRING,
            meta_info STRING,
            relative_path STRING,
            USERNAME STRING,
            CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
    )""").collect()

    session.sql(f"""
        INSERT INTO {table_name} (RAGQuestion, RAGAnswer, file_url, chunk, language, meta_info, relative_path, USERNAME) 
        VALUES (?,?,?,?,?,?,?,?)
    """, [
        question, answer, file_url, chunk, language, meta_info, relative_path, st.experimental_user.user_name
    ]).collect()

def main():
    session = get_active_session()
    init_session_state()
    init_service_metadata(session)
    init_config_options()

    st.title("Chatbot leveraging Snowflake Cortex")
    st.markdown(f"Model: `{st.session_state.model_name}`")

    icons = {"assistant": "❄️", "user": "👤"}

    st.markdown("""
    ##### This Snowflake Cortex RAG Chatbot allows you to ask questions about your PDFs
    Here are some example questions to inspire you:
    - What is the Snowflake Arctic Cookbook Series?
    - What is the Snowflake Arctic-Embed model?
    - What use case does Snowflake Arctic-TILT model support?
    
    Now, it's your turn. Ask your question below or select from this list:""")

    selected_question = st.selectbox(
        "Select a question:", 
        [""] + ALL_QUERIES, 
        key=f"selected_question_{st.session_state.selected_question_key}"
    )

    user_question_input = st.text_input("Enter your question:", value=st.session_state.user_question, key=f"user_question_{st.session_state.question_key}")

    query_to_process = user_question_input or selected_question

    if query_to_process:
        st.session_state.messages.append({"role": "user", "content": query_to_process})
        with st.chat_message("user", avatar=icons["user"]):
            st.markdown(query_to_process.replace("$", "\$"))

        with st.chat_message("assistant", avatar=icons["assistant"]):
            message_placeholder = st.empty()
            prompt_context, results = query_cortex_search_service(session, query_to_process, columns=["chunk", "relative_path"])
            prompt = generate_prompt(query_to_process, results)

            with st.spinner("Thinking..."):
                st.session_state.generated_response = complete(st.session_state.model_name, prompt)
                st.session_state.results = results

                # Extract details for display
                file_url = results[0].get('file_url') if results else None
                chunk = results[0].get('chunk') if results else None
                relative_path = results[0].get('relative_path') if results else None
                language = results[0].get('language') if results else None
                meta_info = results[0].get('meta_info') if results else None

                unique_titles = set(ref['relative_path'] for ref in results)
                markdown_table = "###### References \n\n| PDF Title |\n|-------|\n"
                for title in unique_titles:
                    markdown_table += f"| {title} |\n"
                
                message_placeholder.markdown(st.session_state.generated_response + "\n\n" + markdown_table)

    st.session_state.messages.append({"role": "assistant", "content": st.session_state.generated_response})

    if st.session_state.generated_response and st.checkbox("See PDF?"):
        unique_titles = set(ref['relative_path'] for ref in st.session_state.results)
        st.session_state.pdf_filename = st.selectbox('Select a PDF to view:', list(unique_titles), key="pdf_select_results")

        if st.session_state.pdf_filename:
            st.subheader(f"Preview of {st.session_state.pdf_filename}")
            display_pdf(st.session_state.pdf_filename)
    
    if st.session_state.generated_response:
        if st.checkbox("Save this response to Snowflake?"):
            user_question = st.text_area("Question to save. Modify if needed:", value=textwrap.dedent(query_to_process).strip())
            modified_answer = st.text_area("Answer to save. Modify if needed:", value=textwrap.dedent(st.session_state.generated_response).strip())
            
            if st.button("Update Snowflake table"):
                save_to_snowflake(
                    session, 
                    "TALK_TO_DOC.PUBLIC.qa_table", 
                    user_question, 
                    modified_answer,
                    file_url,
                    chunk,
                    language,
                    meta_info,
                    relative_path)
                st.success("Saved to Snowflake successfully!")

if __name__ == "__main__":
    session = get_active_session()
    root = Root(session)
    main()