import json
import logging
import requests
import polars as pl
from polars import col as C
import dotenv


### Client class for GoCardless API
### This class handles authentication, token management, and generic API requests through GET and POST methods.
### Upon initialization it will try to get a list of institutions after authentication.
class Client:
    _base_url = "https://bankaccountdata.gocardless.com/api/v2/"
    _secret_id = dotenv.get_key('.env', 'GOCARDLESS_SECRET_ID')
    _secret_key = dotenv.get_key('.env', 'GOCARDLESS_SECRET_KEY')

    _token_file = "token.json"
    token: None | dict[str, str] = None

    def __init__(self):
        if not self.try_load_token():
            if not self.try_get_new_token():
                raise Exception("Failed to load token or to get a new token")
        if not self.try_fetch_institutions():
            if not self.try_refresh_token():
                raise Exception(
                    "Failed to fetch institutions and failed to refresh token"
                )
            if not self.try_fetch_institutions():
                raise Exception("Failed to fetch institutions after refreshing token")
        logging.getLogger().info("Successfully authenticated and fetched institutions")

    def try_load_token(self):
        try:
            with open(self._token_file, "r") as f:
                self.token = json.load(f)
            return True
        except Exception as ex:
            logging.getLogger().info(f"Tried to load {self._token_file}. Failed: {ex}")
            return False

    def save_token(self):
        with open(self._token_file, "w") as f:
            json.dump(self.token, f)

    def try_get_new_token(self):
        response = requests.post(
            self._base_url + "token/new/",
            json={
                "secret_id": self._secret_id,
                "secret_key": self._secret_key,
            },
            headers={
                "Accept": "Application/json",
                "Content-Type": "application/json",
            },
        )
        if response.status_code == 200:
            self.token = response.json()
            self.save_token()
            return True
        else:
            logging.getLogger().info(
                f"Failed to get new token: {response.status_code} {response.json()}"
            )
            return False

    # GET with authorization
    def get(
        self,
        endpoint: str,
        params: dict[str, str] | None = None,
    ):
        if not self.token:
            logging.getLogger().info("No token")
            return None
        response = requests.get(
            self._base_url + endpoint,
            params,
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + self.token["access"],
            },
        )
        if response.status_code == 200:
            return response.json()
        else:
            logging.getLogger().info(
                f"GET {endpoint} failed: {response.status_code} {response.json()}"
            )
            return None

    # POST with authorization
    def post(self, endpoint: str, data):
        if not self.token:
            logging.getLogger().info("No token")
            return None
        response = requests.post(
            self._base_url + endpoint,
            json=data,
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + self.token["access"],
                "Content-Type": "application/json",
            },
        )
        if response.status_code == 200 or response.status_code == 201:
            return response.json()
        else:
            logging.getLogger().info(
                f"POST {endpoint} failed: {response.status_code} {response.json()}"
            )
            return None

    # DELETE with authorization
    def delete(self, endpoint: str):
        if not self.token:
            logging.getLogger().info("No token")
            return None
        response = requests.delete(
            self._base_url + endpoint,
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + self.token["access"],
            },
        )
        if response.status_code == 200:
            return response.json()
        else:
            logging.getLogger().info(
                f"DELETE {endpoint} failed: {response.status_code} {response.json()}"
            )
            return None

    def try_fetch_institutions(self):
        response = self.get("institutions/?country=GB")
        if not response:
            return False
        self.institutions = pl.from_dicts(
            response, infer_schema_length=None
        ).with_columns(
            C("transaction_total_days").cast(pl.Int32),
            C("max_access_valid_for_days").cast(pl.Int32),
        )
        return True

    def try_refresh_token(self):
        if not self.token:
            return False
        if not self.token.get("refresh"):
            return False
        response = self.post("token/refresh/", {"refresh": self.token["refresh"]})
        if response:
            self.token["access"] = response["access"]
            self.save_token()
            return True
        else:
            return False
