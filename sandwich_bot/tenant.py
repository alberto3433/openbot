"""
Multi-tenant configuration and database management.

This module handles:
- Loading tenant configuration from JSON
- Resolving tenant from incoming requests (port/domain)
- Providing tenant-specific database sessions
"""

import json
import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Generator, Optional, Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base

logger = logging.getLogger(__name__)

# Context variable to track current tenant in async/threaded contexts
_current_tenant: ContextVar[Optional[str]] = ContextVar("current_tenant", default=None)


@dataclass
class TenantConfig:
    """Configuration for a single tenant."""
    slug: str
    name: str
    database_url: str
    port: int
    domains: list = field(default_factory=list)
    company_settings: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, slug: str, data: Dict[str, Any]) -> "TenantConfig":
        return cls(
            slug=slug,
            name=data.get("name", slug),
            database_url=data["database_url"],
            port=data.get("port", 8000),
            domains=data.get("domains", []),
            company_settings=data.get("company_settings", {}),
        )


class TenantManager:
    """
    Manages multi-tenant configuration and database connections.

    Usage:
        manager = TenantManager.from_json("tenants.json")
        tenant = manager.get_tenant("sammys")
        db = manager.get_db_session("sammys")
    """

    def __init__(self):
        self.tenants: Dict[str, TenantConfig] = {}
        self.default_tenant: Optional[str] = None
        self._engines: Dict[str, Engine] = {}
        self._session_factories: Dict[str, sessionmaker] = {}
        self._port_to_tenant: Dict[int, str] = {}
        self._domain_to_tenant: Dict[str, str] = {}

    @classmethod
    def from_json(cls, config_path: str) -> "TenantManager":
        """Load tenant configuration from a JSON file."""
        manager = cls()

        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Tenant config not found: {config_path}")

        with open(path, "r") as f:
            config = json.load(f)

        manager.default_tenant = config.get("default_tenant")

        for slug, tenant_data in config.get("tenants", {}).items():
            tenant = TenantConfig.from_dict(slug, tenant_data)
            manager.register_tenant(tenant)

        logger.info(
            "Loaded %d tenant(s) from %s, default: %s",
            len(manager.tenants),
            config_path,
            manager.default_tenant,
        )

        return manager

    def register_tenant(self, tenant: TenantConfig) -> None:
        """Register a tenant configuration."""
        self.tenants[tenant.slug] = tenant

        # Build lookup indexes
        self._port_to_tenant[tenant.port] = tenant.slug
        for domain in tenant.domains:
            self._domain_to_tenant[domain.lower()] = tenant.slug

        logger.debug(
            "Registered tenant: %s (port=%d, domains=%s)",
            tenant.slug,
            tenant.port,
            tenant.domains,
        )

    def get_tenant(self, slug: str) -> Optional[TenantConfig]:
        """Get tenant configuration by slug."""
        return self.tenants.get(slug)

    def resolve_tenant_from_request(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> Optional[str]:
        """
        Resolve tenant slug from request information.

        Resolution order:
        1. Full host:port match in domains
        2. Host-only match in domains
        3. Port match
        4. Default tenant
        """
        # Try full host:port match
        if host:
            host_lower = host.lower()
            if host_lower in self._domain_to_tenant:
                return self._domain_to_tenant[host_lower]

            # Try host without port
            host_without_port = host_lower.split(":")[0]
            if host_without_port in self._domain_to_tenant:
                return self._domain_to_tenant[host_without_port]

        # Try port match
        if port and port in self._port_to_tenant:
            return self._port_to_tenant[port]

        # Fall back to default
        return self.default_tenant

    def _get_or_create_engine(self, tenant_slug: str) -> Engine:
        """Get or create SQLAlchemy engine for a tenant."""
        if tenant_slug not in self._engines:
            tenant = self.get_tenant(tenant_slug)
            if not tenant:
                raise ValueError(f"Unknown tenant: {tenant_slug}")

            # Ensure data directory exists for SQLite databases
            db_url = tenant.database_url
            if db_url.startswith("sqlite:///"):
                db_path = db_url.replace("sqlite:///", "")
                if db_path.startswith("./"):
                    db_path = db_path[2:]
                db_dir = os.path.dirname(db_path)
                if db_dir:
                    os.makedirs(db_dir, exist_ok=True)

            engine = create_engine(
                db_url,
                connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
                echo=False,  # Set to True for SQL debugging
            )

            # Create tables if they don't exist
            Base.metadata.create_all(bind=engine)

            self._engines[tenant_slug] = engine
            logger.info("Created database engine for tenant: %s", tenant_slug)

        return self._engines[tenant_slug]

    def _get_or_create_session_factory(self, tenant_slug: str) -> sessionmaker:
        """Get or create session factory for a tenant."""
        if tenant_slug not in self._session_factories:
            engine = self._get_or_create_engine(tenant_slug)
            self._session_factories[tenant_slug] = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=engine,
            )
        return self._session_factories[tenant_slug]

    def get_db_session(self, tenant_slug: str) -> Session:
        """Create a new database session for a tenant."""
        factory = self._get_or_create_session_factory(tenant_slug)
        return factory()

    def get_db_dependency(self, tenant_slug: str) -> Generator[Session, None, None]:
        """
        FastAPI dependency that yields a tenant-specific database session.

        Usage in FastAPI:
            @app.get("/items")
            def get_items(db: Session = Depends(lambda: manager.get_db_dependency("sammys"))):
                ...
        """
        db = self.get_db_session(tenant_slug)
        try:
            yield db
        finally:
            db.close()

    def list_tenants(self) -> list:
        """List all registered tenant slugs."""
        return list(self.tenants.keys())


# Global tenant manager instance (initialized on first use)
_tenant_manager: Optional[TenantManager] = None


def get_tenant_manager() -> TenantManager:
    """Get the global tenant manager instance."""
    global _tenant_manager
    if _tenant_manager is None:
        # Default config path - can be overridden via environment variable
        config_path = os.environ.get("TENANT_CONFIG", "tenants.json")
        _tenant_manager = TenantManager.from_json(config_path)
    return _tenant_manager


def set_tenant_manager(manager: TenantManager) -> None:
    """Set the global tenant manager instance (for testing)."""
    global _tenant_manager
    _tenant_manager = manager


def get_current_tenant() -> Optional[str]:
    """Get the current tenant slug from context."""
    return _current_tenant.get()


def set_current_tenant(tenant_slug: str) -> None:
    """Set the current tenant slug in context."""
    _current_tenant.set(tenant_slug)


def clear_current_tenant() -> None:
    """Clear the current tenant from context."""
    _current_tenant.set(None)
