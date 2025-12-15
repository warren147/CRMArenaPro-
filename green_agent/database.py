# green_agent/database.py

from typing import Dict, Any, List
import re
import logging
from datasets import load_dataset

logger = logging.getLogger("green.database")

class MockSalesforceDB:
    def __init__(self):
        self.tables: Dict[str, List[Dict[str, Any]]] = {}
        self.schema_metadata: Dict[str, Any] = {}
        self._load_schema_from_hf()
        self._seed_minimal_demo_data()

    def _load_schema_from_hf(self):
        try:
            logger.info("Downloading Schema from Hugging Face...")
            dataset_dict = load_dataset("Salesforce/CRMArenaPro", "b2b_schema")
            available_splits = list(dataset_dict.keys())

            if not available_splits:
                raise ValueError("No splits found in schema dataset")

            split_name = available_splits[0]

            logger.info(f"Using schema split: {split_name}")

            dataset = dataset_dict[split_name]

            for row in dataset:
                table_name = row.get("table") or row.get("object")

                if table_name:
                    if table_name not in self.tables:
                        self.tables[table_name] = []
                        self.schema_metadata[table_name] = []

                    self.schema_metadata[table_name].append(row)

            logger.info(f"Initialized {len(self.tables)} tables from Schema: {list(self.tables.keys())}")

        except Exception as e:
            logger.error(f"Failed to load HF Schema: {e}. Falling back to manual seed.")

            self.tables = {"Account": [], "Case": [], "Contact": [], "Opportunity": []}

    def _seed_minimal_demo_data(self):
        if "Case" in self.tables:
            self.tables["Case"].append({
                "Id": "500-DEMO-001",
                "CaseNumber": "00001001",
                "Subject": "Billing Error",
                "Status": "New",
                "Priority": "High",
                "Description": "Customer was overcharged.",
                "Type": "Billing"
            })

        if "Account" in self.tables:
            self.tables["Account"].append({
                "Id": "001-DEMO-999",
                "Name": "Acme Corp",
                "Industry": "Technology",
                "Phone": "555-0100"
            })

    def load_data_from_json(self, filepath: str):
        import json
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                for table, rows in data.items():
                    if table in self.tables:
                        self.tables[table].extend(rows)
                    else:
                        self.tables[table] = rows
            logger.info(f"Loaded external data from {filepath}")
        except FileNotFoundError:
            logger.warning(f"Data file {filepath} not found. DB is empty.")

    def execute_soql(self, query: str) -> Dict[str, Any]:
        """
        Executes a basic mock SOQL query.
        Supports: SELECT fields FROM table WHERE key='val'
        """
        query = query.strip()
        match = re.search(r"SELECT\s+(.+?)\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+))?", query, re.IGNORECASE)

        if not match:
            return {"totalSize": 0, "records": [], "error": "Malformed SOQL"}

        fields_str, table_name, where_clause = match.groups()
        fields = [f.strip() for f in fields_str.split(",")]

        target_table = None

        for t_name in self.tables:
            if t_name.lower() == table_name.lower():
                target_table = self.tables[t_name]

                break

        if target_table is None:
            return {"totalSize": 0, "records": [], "error": f"Table {table_name} not found"}

        filtered_records = target_table

        if where_clause:
            if "=" in where_clause:
                key, val = where_clause.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'").strip('"')
                filtered_records = [r for r in filtered_records if str(r.get(key)) == val]
            elif "LIKE" in where_clause:
                key, val = where_clause.split("LIKE", 1)
                key = key.strip()
                val = val.strip().strip("'").strip('"').replace("%", "")
                filtered_records = [r for r in filtered_records if val.lower() in str(r.get(key, "")).lower()]

        final_result = []

        for r in filtered_records:
            if "*" in fields:
                final_result.append(r)
            else:
                projected = {k: r.get(k) for k in fields if k in r}

                if "Id" not in projected and "Id" in r:
                    projected["Id"] = r["Id"]

                final_result.append(projected)

        return {"totalSize": len(final_result), "records": final_result}

    def execute_sosl(self, query: str) -> Dict[str, Any]:
        match = re.search(r"FIND\s+\{(.+?)\}", query, re.IGNORECASE)

        if not match:
            return {"searchRecords": []}

        search_term = match.group(1).lower()
        results = []

        for table_name, rows in self.tables.items():
            for row in rows:
                if search_term in str(row.values()).lower():
                    results.append({"attributes": {"type": table_name}, **row})

        return {"searchRecords": results}

db = MockSalesforceDB()
