"""Instruction for the first call of a session: map the material into subtopics."""

TOPIC_MAP_INSTRUCTION = """\
<task>Build a topic map for this study session.</task>

Read the material and the coverage request, then return:
- `title`: a short session title (at most 8 words), e.g. "Thermodynamics: First Law and Enthalpy".
- `summary`: one or two sentences describing what the session covers.
- `subtopics`: 3 to 8 subtopics that together cover what the student asked for. Each subtopic \
should be something the student can be tested on, and narrow enough that a weak score on it \
points to a specific area to study, e.g. "Entropy change of ideal gases" rather than "Entropy". \
Give each a name (at most 6 words) and a one-sentence description of the concepts and skills it \
includes. Order them as they appear in the material.

If the coverage request is narrower than the documents (for example "only chapter 3" or "just \
the Laplace transform part"), map only the requested part. If the material is short, use fewer \
subtopics rather than splitting hairs.
"""
