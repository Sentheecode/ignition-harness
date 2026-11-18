"""Research-only thin adapters. Importing/constructing them never connects a Gateway."""
from .archive import ProjectConflict, changed_project_paths, patch_existing_view
from .core import AdapterError, BETA, HTTP, IdentityStates, LabTarget, Status
from .mcp import Catalyst
from .rest import Rest, perspective_client_path, validated_project

__all__ = ['ResearchAdapter', 'LabTarget', 'Status', 'AdapterError', 'ProjectConflict', 'changed_project_paths', 'patch_existing_view']


class ResearchAdapter:
    def __init__(self, target, project, *, rest_headers, mcp_endpoint=None, mcp_headers=None):
        if not isinstance(target, LabTarget):
            raise AdapterError('validated_lab_target_required')
        self.target = target
        self._project = validated_project(project)
        self.identities = IdentityStates()
        http = HTTP(target)
        self.rest = Rest(http, target.version, self._project, rest_headers)
        self.mcp = Catalyst(http, target, self.identities, mcp_endpoint, {} if mcp_headers is None else mcp_headers)

    @property
    def capabilities(self):
        return {'catalyst_contract': self.target.version == BETA,
                'artek_mcp_verified': False, 'designer_login': False,
                'realtime_subscription': False, 'atomic_project_write': False,
                'preview_observed': False, 'database_inspector': False}

    def preview_url(self):
        # URL generation only. It proves neither login nor runtime readiness.
        return self.target.base_url + perspective_client_path(self._project)
