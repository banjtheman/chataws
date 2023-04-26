import pinecone
import openai
import tiktoken
import numpy as np
import pickle
import os

EMBEDDING_MODEL = "text-embedding-ada-002"
PINECONE_KEY = os.environ["PINECONE_KEY"]
PINECONE_INDEX = os.environ["PINECONE_INDEX"]
PINECONE_ENV = os.environ["PINECONE_ENV"]

MAX_SECTION_LEN = 1500
SEPARATOR = "\n* "
ENCODING = "cl100k_base"  # encoding for text-embedding-ada-002
GPT_MODEL = "gpt-3.5-turbo"  # only matters in so far as it selects which tokenizer to use

openai.api_key = os.environ["OPEN_AI_KEY"]
pinecone.init(api_key=PINECONE_KEY, environment=PINECONE_ENV)
index = pinecone.Index(PINECONE_INDEX)

encoding = tiktoken.get_encoding(ENCODING)
separator_len = len(encoding.encode(SEPARATOR))


def get_num_tokens(text: str, model: str = GPT_MODEL) -> int:
    """Return the number of tokens in a string."""
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text))


def load_embeddings(fname):
    with open(fname, "rb") as file:
        # Call load method to deserialze
        document_embeddings = pickle.load(file)

    return document_embeddings


def get_embedding(text: str, model: str = EMBEDDING_MODEL) -> list[float]:
    result = openai.Embedding.create(model=model, input=text)
    return result["data"][0]["embedding"]


def vector_similarity(x: list[float], y: list[float]) -> float:
    """
    Returns the similarity between two vectors.

    Because OpenAI Embeddings are normalized to length 1, the cosine similarity is the same as the dot product.
    """
    return np.dot(np.array(x), np.array(y))


def order_document_sections_by_query_similarity(
    query: str, contexts: dict[(str, str), np.array]
) -> list[(float, (str, str))]:
    """
    Find the query embedding for the supplied query, and compare it against all of the pre-calculated document embeddings
    to find the most relevant sections.

    Return the list of document sections, sorted by relevance in descending order.
    """
    query_embedding = get_embedding(query)

    document_similarities = sorted(
        [
            (vector_similarity(query_embedding, doc_embedding), doc_index)
            for doc_index, doc_embedding in contexts.items()
        ],
        reverse=True,
    )

    return document_similarities


def construct_prompt(question: str) -> str:
    """
    Fetch relevant
    """

    vector = get_embedding(question)
    query_result_content = index.query(
        vector,
        top_k=20,
        include_metadata=True,
    )

    chosen_sections = []
    chosen_sections_len = 0
    chosen_sections_indexes = []

    for result in query_result_content.matches:
        # print(
        #     f"{result.metadata['source_id']} ({result.score}) \n + {result.metadata['text']}"
        # )
        # Add contexts until we run out of space.

        text = result.metadata["text"]
        section_index = {
            "title": result.metadata["source_id"],
            "url": result.metadata["url"],
        }

        # Location of values
        num_tokens = get_num_tokens(text)

        chosen_sections_len += +num_tokens + separator_len
        if chosen_sections_len > MAX_SECTION_LEN:
            break

        chosen_sections.append(SEPARATOR + text.replace("\n", " "))
        chosen_sections_indexes.append(str(section_index))

    # Useful diagnostic information
    # print(f"Selected {len(chosen_sections)} document sections:")
    # print("\n".join(chosen_sections_indexes))

    context = "".join(chosen_sections)

    return (
        context,
        chosen_sections_indexes,
    )
