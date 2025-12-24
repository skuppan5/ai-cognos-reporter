import requests, json, os, sqlite3, argparse
from datetime import datetime
from typing import List, Dict
from dataclasses import dataclass

@dataclass
class CognosReport:
    store_id: str
    name: str
    path: str
    description: str
    parameters: List[str]
    last_modified: str

class AIReporter:
    def __init__(self, cognos_config: Dict):
        self.cognos_url = cognos_config['base_url']
        self.cognos_user = cognos_config['username']
        self.cognos_pass = cognos_config['password']
        self.session = requests.Session()
        self.reports_db = "cognos_reports_cache.db"
        self._authenticate_cognos()
        self._build_reports_cache()
    
    def _authenticate_cognos(self):
        login_url = f"{self.cognos_url}/v1/authorize"
        payload = {"CAMNamespace": "cognos", "parameters": [
            {"name": "userId", "value": self.cognos_user},
            {"name": "password", "value": self.cognos_pass}
        ]}
        self.session.post(login_url, json=payload).raise_for_status()
        print("✅ Cognos authenticated")
    
    def _build_reports_cache(self):
        conn = sqlite3.connect(self.reports_db)
        conn.execute('''CREATE TABLE IF NOT EXISTS reports 
            (store_id TEXT PRIMARY KEY, name TEXT, path TEXT, description TEXT,
            parameters TEXT, last_modified TEXT)''')
        
        search_url = f"{self.cognos_url}/api/v1/search"
        payload = {"query": {"searchText": "*", "objectTypes": ["report"]}, "count": 1000}
        resp = self.session.post(search_url, json=payload)
        results = resp.json().get('results', [])
        
        for item in results:
            conn.execute('''INSERT OR REPLACE INTO reports VALUES (?, ?, ?, ?, ?, ?)''',
                        (item['id'], item['name'], item['path'], 
                         item.get('description', ''), json.dumps([]), item.get('lastModified', '')))
        conn.commit()
        conn.close()
        print(f"✅ Cached {len(results)} reports")
    
    def search_reports(self, query: str) -> List[CognosReport]:
        conn = sqlite3.connect(self.reports_db)
        cursor = conn.execute('''SELECT * FROM reports 
            WHERE name LIKE ? OR description LIKE ? OR path LIKE ?''',
            (f"%{query}%", f"%{query}%", f"%{query}%"))
        reports = [CognosReport(*row[:-1], json.loads(row[-1])) for row in cursor.fetchall()]
        conn.close()
        return reports
    
    def generate_report(self, store_id: str, params: Dict = None, fmt: str = "pdf") -> str:
        run_url = f"{self.cognos_url}/v1/reports/{store_id}/runs"
        payload = {"parameters": [{"name": k, "value": v} for k, v in (params or {}).items()], 
                  "outputFormat": fmt}
        resp = self.session.post(run_url, json=payload)
        run_info = resp.json()
        output_url = run_info['output']['url']
        
        filename = f"report_{store_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}"
        filepath = f"/tmp/{filename}"
        with open(filepath, 'wb') as f:
            f.write(self.session.get(output_url).content)
        return filepath

class AIReportAgent:
    def __init__(self, reporter): self.reporter = reporter
    
    def process_request(self, request: str) -> str:
        reports = self.reporter.search_reports(request)
        if not reports: return "❌ No reports found"
        best = max(reports, key=lambda r: self._score_report(r, request))
        params = self._extract_params(request)
        filepath = self.reporter.generate_report(best.store_id, params)
        return f"✅ {best.name}\n📄 {filepath}\n📊 {params}"
    
    def _score_report(self, report, request): 
        return sum(1 for word in request.lower().split() if word in (report.name + report.description).lower())
    
    def _extract_params(self, request: str) -> Dict:
        params, r = {}, request.lower()
        if any(x in r for x in ['dec', '2024']): params['p_Date'] = '2024-12'
        if 'q4' in r: params['p_Quarter'] = 'Q4'
        return params

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Cognos Report Bot")
    parser.add_argument('--request', help="Report request")
    parser.add_argument('--interactive', action='store_true')
    args = parser.parse_args()
    
    cognos_config = {
        "base_url": os.getenv('COGNOS_URL', 'https://yourtenant.cognosanalytics.ibmcloud.com/bi'),
        "username": os.getenv('COGNOS_USER'),
        "password": os.getenv('COGNOS_PASS')
    }
    
    reporter = AIReporter(cognos_config)
    agent = AIReportAgent(reporter)
    
    if args.interactive:
        while True:
            req = input("\n🤖 Ask for report: ")
            if req.lower() == 'quit': break
            print(agent.process_request(req))
    else:
        print(agent.process_request(args.request or "daily sales"))
