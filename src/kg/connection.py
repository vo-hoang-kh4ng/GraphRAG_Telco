"""Thin wrapper around the Neo4j Python driver used across the project."""

import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


class Neo4jConnection:
    """Context-manager wrapper exposing a single `run` helper for Cypher queries."""

    def __init__(self, uri=None, user=None, password=None):
        self._uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self._user = user or os.getenv("NEO4J_USER", "neo4j")
        self._password = password or os.getenv("NEO4J_PASSWORD", "telco12345")
        self._driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))

    def close(self):
        self._driver.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def verify_connectivity(self):
        self._driver.verify_connectivity()

    def run(self, query, parameters=None):
        """Run a Cypher query and return a list of plain dicts (records)."""
        with self._driver.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]

    def run_write(self, query, parameters=None):
        """Run a Cypher query inside an explicit write transaction."""
        with self._driver.session() as session:
            return session.execute_write(lambda tx: [r.data() for r in tx.run(query, parameters or {})])
