# AI as-is architecture

**Artifact:** ai_as_is_architecture
**Source:** cafe-artifacts.xlsx
**Rendered:** imported from the source above by scripts/artifacts_workbook.py

| service name | consumers | offered behaviour | current service level | owned entities | failure semantics | operator |
|---|---|---|---|---|---|---|
| Patient LLM (Med42) | Sahatna Chatbot module | Healthcare AI chatbot backbone, patient query handling, clinical decision support | not stated | Chat conversations, patient queries | Graceful degradation to FAQ fallback | M42 AI Operations |
| Isabel AI Service | Symptoms-Checker Service | AI-powered clinical decision support, symptom analysis, multi-symptom diagnosis suggestions | not stated | Symptom assessments, diagnostic suggestions | Fallback to general guidance | Isabel Healthcare (external) |
| Fractal AI Service | Healthcare analytics | Advanced healthcare data analysis, pattern recognition, predictive modeling | not stated | Predictive models, clinical insights | not stated | M42 AI Operations |
| Genomics AI (Gensense) | Sahatna Genomics Service | Personalized genetic analysis, health risk predictions, microbiome composition | not stated | Genetic profiles, risk assessments | not stated | M42 Genomics |
