# Sahkaar Saathi

Sahkaar Saathi is a multilingual voice and text assistant designed to help farmers, cooperative members, and rural users understand cooperative laws, schemes, PACS services, crop insurance processes, and grievance procedures.

It uses official government documents to provide grounded, source-backed answers in English, Hindi, Kannada, and Marathi.

## Features

- Multilingual support: English, Hindi, Kannada, Marathi
- Voice input using Bhashini ASR
- Translation and TTS support
- Jurisdiction-aware RAG
- Source-backed answers with citations
- Cite-or-abstain behavior when evidence is insufficient
- Cooperative law guidance
- PMFBY guidance
- PACS-related information
- Cooperative Ombudsman and grievance support
- Context-aware follow-up questions

## Tech Stack

- Frontend: React + Vite
- Backend: FastAPI
- LLM: Groq
- Embeddings: multilingual-e5-small
- Vector Search: FAISS
- Language Services: Bhashini
- Knowledge Base: Official government Acts, Rules, Guidelines and scheme documents

## System Flow

User Voice / Text  
↓  
Bhashini ASR + Translation  
↓  
Jurisdiction Router  
↓  
RAG Retrieval  
↓  
Official Government Corpus  
↓  
Grounded LLM Answer  
↓  
Citations / Abstain  
↓  
Bhashini TTS

## Supported Knowledge Areas

- Karnataka Cooperative Societies Act
- Maharashtra Cooperative Societies Act and Rules
- Multi-State Cooperative Societies Act and Rules
- PACS Model Bye-Laws and Computerization Guidelines
- PMFBY Operational Guidelines
- Cooperative Ombudsman / Grievance Guidance

## Project Structure

```text
SahkaarSaathi/
├── backend/
├── data/
├── frontend/
├── scripts/
├── requirements.txt
├── .env.example
└── README.md
