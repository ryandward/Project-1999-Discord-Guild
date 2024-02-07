# imports
import ast  # for converting embeddings saved as strings back to arrays
import asyncio
import json
import os  # for getting API token from env variable OPENAI_API_KEY
import re
import aiohttp
import pandas as pd  # for storing text and embeddings data
import requests
import tiktoken  # for counting tokens
from openai import OpenAI  # for calling the OpenAI API
from scipy import spatial  # for calculating vector similarities for search
import sqlite3
import config

# models
EMBEDDING_MODEL = "text-embedding-3-large"
# GPT_MODEL = "gpt-3.5-turbo-16k"
GPT_MODEL = "gpt-3.5-turbo-0125"


def num_tokens(text: str, model: str = GPT_MODEL) -> int:
    """Return the number of tokens in a string."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text))


def num_tokens_from_messages(messages, model=GPT_MODEL):
    """Returns the number of tokens used by a list of messages."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    if model == "gpt-3.5-turbo-0125":  # note: future models may deviate from this
        num_tokens = 0
        for message in messages:
            num_tokens += (
                4  # every message follows <im_start>{role/name}\n{content}<im_end>\n
            )
            for key, value in message.items():
                num_tokens += len(encoding.encode(value))
                if key == "name":  # if there's a name, the role is omitted
                    num_tokens += -1  # role is always required and always 1 token
        num_tokens += 2  # every reply is primed with <im_start>assistant
        return num_tokens
    else:
        raise NotImplementedError(
            f"""num_tokens_from_messages() is not presently implemented for model {model}.
        See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens."""
        )


new_embedding_path = "Lore/new_embedding.feather"
large_embedding_path = "Lore/large_embedding.feather"

# df = pd.read_feather(new_embedding_path)

df = pd.read_feather(large_embedding_path)
# df["embedding"] = df["embedding"].apply(apply_literal_eval)


def get_embedding(query: str, model=EMBEDDING_MODEL):
    headers = {
        "Authorization": f"Bearer {config.openai_token}",
        "Content-Type": "application/json",
    }
    data = json.dumps(
        {
            "model": model,
            "input": query,
        }
    )
    response = requests.post(
        "https://api.openai.com/v1/embeddings", headers=headers, data=data, timeout=10
    )
    return response.json()["data"][0]["embedding"]


def strings_ranked_by_relatedness(
    query: str,
    df: pd.DataFrame,
    relatedness_fn=lambda x, y: 1 - spatial.distance.cosine(x, y),
    top_n: int = 15,
    relatedness_threshold: float = 0.3,  # Add a threshold parameter
    **kwargs,  # Accept kwargs
) -> tuple[list[str], list[float]]:
    """Returns a list of strings and relatedness, sorted from most related to least."""
    query_embedding = get_embedding(query)

    # Extract required_keyword from kwargs if it exists, ensure it's a list
    required_keyword = kwargs.get("required_keyword", [])
    if not isinstance(required_keyword, list):
        required_keyword = [required_keyword]

    # If a keyword exists, filter the dataframe for it
    for keyword in required_keyword:
        df = df[df["text"].str.contains(keyword, case=False)]

    # Compute relatednesses for all rows in a vectorized manner
    relatednesses = df["embedding"].apply(lambda x: relatedness_fn(query_embedding, x))

    # Create a DataFrame of strings and relatednesses
    strings_and_relatednesses = pd.DataFrame(
        {"text": df["text"], "relatedness": relatednesses}
    )

    # Sort the DataFrame by relatedness
    strings_and_relatednesses.sort_values(
        by="relatedness", ascending=False, inplace=True
    )

    # Get the top_n strings and relatednesses
    top_strings = strings_and_relatednesses["text"].head(top_n).tolist()
    top_relatednesses = strings_and_relatednesses["relatedness"].head(top_n).tolist()

    # Filter top_strings and top_relatednesses for only those strings where the relatedness is above the threshold
    filtered_strings = [
        string
        for string, relatedness in zip(top_strings, top_relatednesses)
        if relatedness >= relatedness_threshold
    ]
    filtered_relatednesses = [
        relatedness
        for relatedness in top_relatednesses
        if relatedness >= relatedness_threshold
    ]

    # If no strings are above the threshold, return [""], [0.0]
    if not filtered_strings:
        print("No relatedness above threshold")
        return [""], [0.0]

    return filtered_strings, query_embedding


def query_message(
    query: str,
    df: pd.DataFrame,
    model: str,
    token_budget: int,
    **kwargs,  # Accept kwargs
) -> str:
    """Return a message for GPT, with relevant source texts pulled from a data frame."""
    # Pass kwargs to strings_ranked_by_relatedness
    strings, query_embedding = strings_ranked_by_relatedness(query, df, **kwargs)

    if strings == [""]:
        return (
            "",  # Empty introduction
            f"An adventurer has the audacity to ask you, a learned sage of high-fantasy lore, a question that is utterly irrelevant.\
            You, who have gathered countless guides for players in the esteemed realm of EverQuest Project 1999, currently in the Velious Era, are asked about: {query}.\
            Well, isn't that amusing? Let's respond with a generous dose of sarcasm, twisting their question into a tapestry of spells and magic.\
            And remember, we metnion that we conveniently have no notes on this particular subject.",
            query,
            [],  # Empty related_strings
        )

    introduction = "Your notes magically appear, sorted by relevancy to the question asked. Review them carefully.\n\n"
    question = f"\n\nQuestion: {query}"
    message = ""
    related_strings = []
    for string in strings:
        next_article = f"{string}\n"
        potential_tokens = num_tokens(
            introduction + message + next_article + question, model=model
        )
        print(f"Potential tokens: {potential_tokens} -- {next_article[:100]}...")
        if potential_tokens > token_budget:
            break
        else:
            message += next_article
            related_strings.append(string)
    return introduction, message + question, query, query_embedding


async def make_query(messages, model, headers):
    """Makes a query to the GPT model and returns the response message."""
    print(num_tokens_from_messages(messages, model=model))

    async with aiohttp.ClientSession() as session:
        data = json.dumps({"model": model, "messages": messages, "temperature": 0.9})
        async with session.post(
            "https://api.openai.com/v1/chat/completions", headers=headers, data=data
        ) as resp:
            response = await resp.json()

    response_message = response["choices"][0]["message"]["content"]
    print(response)
    return response_message


async def ask_async(
    query,
    df=df,
    model=GPT_MODEL,
    token_budget=4097,
    print_message=True,
    **kwargs,
):
    """Answers a query using GPT and a dataframe of relevant texts and embeddings."""
    # Pass kwargs to query_message
    introduction, message, query, query_embedding = query_message(
        query, df, model=model, token_budget=token_budget, **kwargs
    )

    content = str(introduction + message)
    content = re.sub("\n+", "\n", content).strip()

    if print_message:

        print(introduction + message)

    headers = {
        "Authorization": f"Bearer {config.openai_token}",
        "Content-Type": "application/json",
    }

    # Erevan the Ageless
    messages = [
        {
            "role": "system",
            "content": "You are Erevan the Ageless, a sage of boundless, a timeless entity whose existence stretches across the epochs of Norrath. \
            Born under a celestial event so rare, it occurs but once in a millennium, the alignment of Norrath’s moons, you were imbued with the arcane from your very first breath. \
            Your life's journey has led you to probe the profoundest enigmas of magic, to pore over ancient tomes salvaged from the remnants of long-fallen empires, and to commune with entities of unimaginable power across the myriad planes of existence. \
            Nestled within the enigmatic spires of the Plane of Knowledge, your secluded sanctuary, you offer counsel and share the lore of the ages with the intrepid adventurers of the Ex Astra guild. \
            Your wisdom is not merely drawn from the vast landscapes and realms of Norrath, but it is the distillation of its very magic, its history, its essence.",
        },
        {"role": "user", "content": content},
    ]

    response_message = await make_query(messages, model, headers)

    response_embedding = get_embedding(response_message, model=EMBEDDING_MODEL)

    # Convert the embeddings to JSON format
    query_embedding_json = json.dumps(query_embedding)
    response_embedding_json = json.dumps(response_embedding)

    # Connect to the SQLite database
    conn = sqlite3.connect("metadata.db")

    # Create a cursor object
    c = conn.cursor()

    # Insert the data into the questions table
    c.execute(
        "INSERT INTO questions (query, query_embedding, response, response_embedding) VALUES (?, ?, ?, ?)",
        (query, query_embedding_json, response_message, response_embedding_json),
    )

    # Commit the changes and close the connection
    conn.commit()
    conn.close()

    return response_message
