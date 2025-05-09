# Pacioli

![Luca Pacioli](https://commons.wikimedia.org/wiki/File:Luca_Pacioli_in_the_Summa.jpg#/media/File:Luca_Pacioli_in_the_Summa.jpg)

[Luca Pacioli](https://en.wikipedia.org/wiki/Luca_Pacioli) is widely regarded as the father of
accounting.

This project is bare-bones spending tracker, using Open Banking APIs, and semi-automated classification via LLMs.
Primary UX are through command lines that need manual set up for cron/repetition, and janky UI
through Jupyter notebooks. 🧑‍🍳😘

Open Banking API is accessed through GoCardless (https://gocardless.com/) so you have to set up
an account there (dev + personal use is free), and sort out an API key. There is a python client
(https://github.com/gocardless/gocardless-pro-python) but it's a bit complex so this implements
a bare-bones API through `requests`.

In order to maintain history of transactions and update them, there is a need to maintain state.
This is effectively kept between GoCardless (through its requisitions and accounts API), and raw
dumps of the bank-provided json (in json files within the `raw` directory) -- with the inner
directory name mapping to the GoCardless account id and therefore linking everything together.

API keys are managed though [`dotenv`](https://github.com/theskumar/python-dotenv). Need to define
the following to be able to get going:
```toml
GOCARDLESS_SECRET_ID = "..."
GOCARDLESS_SECRET_KEY = "..."
OPENAI_API_KEY = "..."
```