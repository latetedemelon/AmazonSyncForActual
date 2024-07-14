import requests

class ActualClient:
    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token
        self.headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }

    def list_recent_transactions(self, days):
        endpoint = f'{self.base_url}/transactions'
        params = {
            'start_date': (date.today() - timedelta(days=days)).isoformat()
        }
        response = requests.get(endpoint, headers=self.headers, params=params)
        return response.json()

    def update_transactions(self, transactions):
        endpoint = f'{self.base_url}/transactions/update'
        response = requests.post(endpoint, headers=self.headers, json={'transactions': transactions})
        return response.json()
