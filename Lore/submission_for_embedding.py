#!/usr/bin/env python
# coding: utf-8

# In[74]:


import concurrent.futures
import os
import re  # for cutting <ref> links out of Wikipedia articles
import sqlite3
import urllib3
import warnings
import sys
import mwclient  # for downloading example Wikipedia articles
import mwparserfromhell  # for splitting Wikipedia articles into sections
import openai  # for generating embeddings
import pandas as pd  # for DataFrames to store article sections and embeddings
import tiktoken  # for counting tokens
import json

from bs4 import BeautifulSoup

from openai import OpenAI

import config


client = OpenAI(api_key=config.openai_token)


conn = sqlite3.connect('../metadata.db')
c = conn.cursor()
c.execute('SELECT title, markdown FROM metadata WHERE pageid IS NOT NULL AND categories NOT LIKE "%Category:Non-P99 Content%"' )
articles = list(c.fetchall())
conn.close()
print(f"Found {len(articles)} article titles in database.")


# In[2]:


GPT_MODEL = "gpt-3.5-turbo-0613"  # only matters insofar as it selects which tokenizer to use

def num_tokens(text: str, model: str = GPT_MODEL) -> int:
    """Return the number of tokens in a string."""
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text))


# In[ ]:





# In[136]:


budget = 750

def json_to_sentences(data):
    """Convert nested JSON data to sentences."""
    if isinstance(data, list):
        for obj in data:
            sentence = ', '.join(f"{key}: {value}" for key, value in obj.items())
            yield sentence

def clean_and_chunk_wikitext(text:str):    
    #get rid of all leading spaces everywhere

    cleaned_lines = []
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if line == "":
            continue
        line = line.replace("NaN", "null")
        line = line.replace(r"\-", "-")

        try:
            data = json.loads(str(line))
            sentences = list(json_to_sentences(data))
            cleaned_lines.extend(sentences)  # use extend instead of append
        except:
            cleaned_lines.append(line)

    cleaned_lines = [line for line in cleaned_lines if line is not None]
    cleaned_text = '\n'.join(cleaned_lines)

    import mwparserfromhell

    sections = []
    section = []
    token_count = 0

    wikicode = mwparserfromhell.parse(cleaned_text)
    for wiki_section in wikicode.get_sections(flat=True):
        n = 1
        heading_nodes = wiki_section.filter_headings()
        heading = str(heading_nodes[0]) if heading_nodes else ""
        if heading.strip() == "":
            continue
        if str(wiki_section.filter_text()).strip() == "":
            continue
        lines = str(wiki_section).split('\n')[1:]
        if len(lines) <= 1:
            continue
        if num_tokens(str(wiki_section)) > budget:
            section = ["= " + heading.replace("=", "").strip() + " - Section " + str(n) + " ="]
        else:
            section = ["= " + heading.replace("=", "").strip() + " ="]
        token_count = num_tokens(heading)
        for line in lines:
            # if line.strip() == "" or heading.strip() == "":
                # continue
        
            line_token_count = num_tokens(line)
            if token_count + line_token_count < budget:
                # Add the line to the current section
                section.append(line)
                token_count += line_token_count
            else:
                n += 1
                # Start a new section
                sections.append('\n'.join(section)+'\n')
                section = ["= " + heading.replace("=", "").strip() + " - Section " + str(n) + " ="]
                token_count = num_tokens(heading)
                section.append(line)
                token_count += line_token_count
        # Add the section when finished with this wiki section
        sections.append('\n'.join(section))
        section = []
        token_count = 0

    # Add the last section
    if section:
        sections.append('\n'.join(section))
    # return sections
    # make one long string
    cleaned_text = '\n'.join(sections)

    #chunk together
    chunks = []
    chunk = []
    token_count = 0

    wikicode = mwparserfromhell.parse(cleaned_text)
    sections = wikicode.get_sections(flat=True)

    for section in sections:
        # section = mwparserfromhell.parse(section)[0]
        # print(section)
        heading = str(section.filter_headings()[0]) if section.filter_headings() else ""
        text = str(section)
        section_token_count = num_tokens(text)
        if token_count + section_token_count < budget:
            # Add the section to the current chunk
            chunk.append(text)
            token_count += section_token_count
        else:
            # Start a new chunk
            chunks.append('\n'.join(chunk))
            chunk = [text]
            token_count = section_token_count
        # Check if the current chunk exceeds the budget and if so, start a new chunk
        if token_count > budget:
            chunks.append('\n'.join(chunk))
            chunk = []
            token_count = 0

    # Add the last chunk
    if chunk:
        chunks.append('\n'.join(chunk))

    cleaned_chunks = []
    for chunk in chunks:
        chunk_code = mwparserfromhell.parse(chunk)
        chunk_sections = chunk_code.get_sections(include_headings=True, flat=True)

        for section in chunk_sections:
            non_heading_nodes = [node for node in section.nodes if not isinstance(node, mwparserfromhell.nodes.heading.Heading)]
            if not non_heading_nodes or str(non_heading_nodes[0]).strip() == "":
                chunk_code.remove(section)

        cleaned_chunks.append(str(chunk_code))
        
    
    shortened_chunks = []
    for chunk in cleaned_chunks:
        chunk = chunk.replace("\n\n+", "\n").replace("\\", "")
        shortened_chunks.append(chunk)
        
    return(shortened_chunks)



# In[140]:


# process the article with a title called "Wizard"

wizard_article = [article for article in articles if article[0] == "10th Coldain Ring Quest"][0]
wizard_title = wizard_article[0]
wizard_text = wizard_article[1]

wizard_chunk = clean_and_chunk_wikitext(wizard_text)

for chunk in wizard_chunk:
    print("---------------", num_tokens(chunk), "---------------")
    print(chunk)


# In[139]:


chunks_to_embed = []
for title, markdown in articles:
    print(title)
    print(f"Processing {title}...")
    chunks = clean_and_chunk_wikitext(markdown)
    chunks_to_embed.extend(chunks)



# In[ ]:


import csv
import logging
import colorlog

handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(asctime)s - %(levelname)s - %(message)s'))

logger = colorlog.getLogger('example')
logger.addHandler(handler)

# split sections into chunks
MAX_TOKENS = 1900  # 2048 is the max for GPT-3, but we want some wiggle room

# OpenAI's best embeddings as of Apr 2023
EMBEDDING_MODEL = "text-embedding-3-large"
embedding_encoding = "cl100k_base"  # this the encoding for text-embedding-ada-002

BATCH_SIZE = 2048  # you can submit up to 2048 embedding inputs per request

# embedding model parameters
max_tokens = 8000  # the maximum for text-embedding-ada-002 is 8191


def get_embedding(text, model=EMBEDDING_MODEL):
    try:
        text = text.replace("\n", " ")
        response = client.embeddings.create(input=[text], model=model).data[0].embedding
        logging.info(f"Received embedding for text: {text[:100]}... Embedding: {response}")
        return response
    except Exception as e:
        logging.error(f"Failed to get embedding for text: {text[:100]}... Error: {e}")
        return None


SAVE_PATH = "large_embedding.feather"
FAIL_PATH = "failed_texts.txt"
successful_texts = []
failed_texts = []

# Check if the file exists and create it if it doesn't
if not os.path.isfile(SAVE_PATH):
    pd.DataFrame(columns=["text", "embedding"]).to_csv(SAVE_PATH, index=False)

import pandas as pd

# Initialize an empty DataFrame
df = pd.DataFrame(columns=['text', 'embedding'])

for batch_start in range(0, len(chunks_to_embed), BATCH_SIZE):
    logging.info(f"Processing batch {batch_start}...")
    batch_end = batch_start + BATCH_SIZE
    batch = chunks_to_embed[batch_start:batch_end]
    logging.info(f"Batch {batch_start} to {batch_end-1}")
    for text in batch:
        try: # main attempt
            embedding = get_embedding(text)
            if embedding is not None:
                # Append the text and its embedding to the DataFrame
                new_row = pd.DataFrame({'text': [text], 'embedding': [embedding]})
                df = pd.concat([df, new_row], ignore_index=True)
            else: # if the embedding is None, add the text to the failed list
                logging.warning(f"Skipping text due to error: {text[:100]}...")
                failed_texts.append(text)
        except Exception as e:
            logging.error(f"Exception when getting embedding for text: {text[:100]}... Error: {e}")
            failed_texts.append(text)

# Write the DataFrame to a Feather file
df.to_feather(SAVE_PATH)

