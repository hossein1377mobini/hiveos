import pgvector.sqlalchemy.vector
"""baseline

Revision ID: 2a44bc6adf74
Revises: 
Create Date: 2026-08-19 16:21:25.161130

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a44bc6adf74'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('tenants',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('display_name', sa.String(length=128), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tenants_slug'), 'tenants', ['slug'], unique=True)
    op.create_table('organizations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=True),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('industry', sa.String(length=100), nullable=False),
    sa.Column('company_size', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('business_description', sa.JSON(), nullable=False),
    sa.Column('ai_mode', sa.String(length=16), nullable=False),
    sa.Column('ai_provider', sa.String(length=64), nullable=False),
    sa.Column('ai_api_key_enc', sa.Text(), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('language', sa.String(length=10), nullable=False),
    sa.Column('time_zone', sa.String(length=32), nullable=False),
    sa.Column('owner_onboard_token_hash', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', name='uq_organizations_tenant_id')
    )
    op.create_index(op.f('ix_organizations_owner_onboard_token_hash'), 'organizations', ['owner_onboard_token_hash'], unique=False)
    op.create_index(op.f('ix_organizations_status'), 'organizations', ['status'], unique=False)
    op.create_index(op.f('ix_organizations_tenant_id'), 'organizations', ['tenant_id'], unique=False)
    op.create_table('owners',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('phone', sa.String(length=16), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', name='uq_owners_one_per_org')
    )
    op.create_index(op.f('ix_owners_organization_id'), 'owners', ['organization_id'], unique=False)
    op.create_index(op.f('ix_owners_phone'), 'owners', ['phone'], unique=True)
    op.create_index(op.f('ix_owners_tenant_id'), 'owners', ['tenant_id'], unique=False)
    op.create_index('uq_owners_email_ci', 'owners', [sa.literal_column('lower(email)')], unique=True, postgresql_where=sa.text('email IS NOT NULL'))
    op.create_table('workspaces',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('settings', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', name='uq_workspaces_one_per_org')
    )
    op.create_index(op.f('ix_workspaces_organization_id'), 'workspaces', ['organization_id'], unique=False)
    op.create_index(op.f('ix_workspaces_tenant_id'), 'workspaces', ['tenant_id'], unique=False)
    op.create_table('otp_codes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('phone', sa.String(length=16), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=True),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('used', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['owners.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_otp_codes_organization_id'), 'otp_codes', ['organization_id'], unique=False)
    op.create_index(op.f('ix_otp_codes_phone'), 'otp_codes', ['phone'], unique=False)
    op.create_index(op.f('ix_otp_codes_tenant_id'), 'otp_codes', ['tenant_id'], unique=False)
    op.create_table('sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['owners.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sessions_organization_id'), 'sessions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_sessions_owner_id'), 'sessions', ['owner_id'], unique=False)
    op.create_index(op.f('ix_sessions_tenant_id'), 'sessions', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_sessions_token_hash'), 'sessions', ['token_hash'], unique=True)
    op.create_table('audit_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('actor_ref', sa.String(length=128), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_tenant_id'), 'audit_logs', ['tenant_id'], unique=False)
    op.create_table('organization_brains',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('embedding_provider', sa.String(length=64), nullable=False),
    sa.Column('default_language', sa.String(length=10), nullable=False),
    sa.Column('retrieval_config', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', name='uq_brains_one_per_org')
    )
    op.create_index(op.f('ix_organization_brains_organization_id'), 'organization_brains', ['organization_id'], unique=False)
    op.create_index(op.f('ix_organization_brains_tenant_id'), 'organization_brains', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_organization_brains_workspace_id'), 'organization_brains', ['workspace_id'], unique=False)
    op.create_table('knowledge_repositories',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('brain_id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['brain_id'], ['organization_brains.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_knowledge_repositories_brain_id'), 'knowledge_repositories', ['brain_id'], unique=False)
    op.create_index(op.f('ix_knowledge_repositories_organization_id'), 'knowledge_repositories', ['organization_id'], unique=False)
    op.create_index(op.f('ix_knowledge_repositories_tenant_id'), 'knowledge_repositories', ['tenant_id'], unique=False)
    op.create_table('vector_indexes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('brain_id', sa.UUID(), nullable=False),
    sa.Column('knowledge_repository_id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('dimensions', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['brain_id'], ['organization_brains.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['knowledge_repository_id'], ['knowledge_repositories.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vector_indexes_brain_id'), 'vector_indexes', ['brain_id'], unique=False)
    op.create_index(op.f('ix_vector_indexes_knowledge_repository_id'), 'vector_indexes', ['knowledge_repository_id'], unique=False)
    op.create_index(op.f('ix_vector_indexes_organization_id'), 'vector_indexes', ['organization_id'], unique=False)
    op.create_index(op.f('ix_vector_indexes_tenant_id'), 'vector_indexes', ['tenant_id'], unique=False)
    # ### end Alembic commands ###


    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('brain_id', sa.UUID(), nullable=True),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('format', sa.String(length=8), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['brain_id'], ['organization_brains.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'filename', name='uq_documents_org_filename')
    )
    op.create_index(op.f('ix_documents_organization_id'), 'documents', ['organization_id'], unique=False)
    op.create_index(op.f('ix_documents_status'), 'documents', ['status'], unique=False)
    op.create_index(op.f('ix_documents_tenant_id'), 'documents', ['tenant_id'], unique=False)
    op.create_table('document_chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('brain_id', sa.UUID(), nullable=False),
    sa.Column('source_document_id', sa.String(length=64), nullable=True),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=False),
    sa.Column('metadata', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['brain_id'], ['organization_brains.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_chunks_brain_id'), 'document_chunks', ['brain_id'], unique=False)
    op.create_index(op.f('ix_document_chunks_organization_id'), 'document_chunks', ['organization_id'], unique=False)
    op.create_index(op.f('ix_document_chunks_tenant_id'), 'document_chunks', ['tenant_id'], unique=False)
    op.create_table('ingestion_folder_configs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('folder_path', sa.Text(), nullable=False),
    sa.Column('watch_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', name='uq_ingestion_folder_one_per_org')
    )
    op.create_index(op.f('ix_ingestion_folder_configs_organization_id'), 'ingestion_folder_configs', ['organization_id'], unique=False)
    op.create_index(op.f('ix_ingestion_folder_configs_tenant_id'), 'ingestion_folder_configs', ['tenant_id'], unique=False)
    op.create_table('processing_jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('job_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_processing_jobs_document_id'), 'processing_jobs', ['document_id'], unique=False)
    op.create_index(op.f('ix_processing_jobs_organization_id'), 'processing_jobs', ['organization_id'], unique=False)
    op.create_index(op.f('ix_processing_jobs_status'), 'processing_jobs', ['status'], unique=False)
    op.create_index(op.f('ix_processing_jobs_tenant_id'), 'processing_jobs', ['tenant_id'], unique=False)
    op.create_table('organization_onboarding',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', name='uq_organization_onboarding_one_per_org')
    )
    op.create_index(op.f('ix_organization_onboarding_organization_id'), 'organization_onboarding', ['organization_id'], unique=False)
    op.create_index(op.f('ix_organization_onboarding_tenant_id'), 'organization_onboarding', ['tenant_id'], unique=False)
    op.create_foreign_key(
        'fk_organizations_workspace_id', 'organizations', 'workspaces', ['workspace_id'], ['id'],
    )
def downgrade() -> None:
    op.drop_constraint('fk_organizations_workspace_id', 'organizations', type_='foreignkey')
    op.drop_index(op.f('ix_organization_onboarding_tenant_id'), table_name='organization_onboarding')
    op.drop_index(op.f('ix_organization_onboarding_organization_id'), table_name='organization_onboarding')
    op.drop_table('organization_onboarding')
    op.drop_index(op.f('ix_processing_jobs_tenant_id'), table_name='processing_jobs')
    op.drop_index(op.f('ix_processing_jobs_status'), table_name='processing_jobs')
    op.drop_index(op.f('ix_processing_jobs_organization_id'), table_name='processing_jobs')
    op.drop_index(op.f('ix_processing_jobs_document_id'), table_name='processing_jobs')
    op.drop_table('processing_jobs')
    op.drop_index(op.f('ix_ingestion_folder_configs_tenant_id'), table_name='ingestion_folder_configs')
    op.drop_index(op.f('ix_ingestion_folder_configs_organization_id'), table_name='ingestion_folder_configs')
    op.drop_table('ingestion_folder_configs')
    op.drop_index(op.f('ix_document_chunks_tenant_id'), table_name='document_chunks')
    op.drop_index(op.f('ix_document_chunks_organization_id'), table_name='document_chunks')
    op.drop_index(op.f('ix_document_chunks_brain_id'), table_name='document_chunks')
    op.drop_table('document_chunks')
    op.drop_index(op.f('ix_documents_tenant_id'), table_name='documents')
    op.drop_index(op.f('ix_documents_status'), table_name='documents')
    op.drop_index(op.f('ix_documents_organization_id'), table_name='documents')
    op.drop_table('documents')
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_vector_indexes_tenant_id'), table_name='vector_indexes')
    op.drop_index(op.f('ix_vector_indexes_organization_id'), table_name='vector_indexes')
    op.drop_index(op.f('ix_vector_indexes_knowledge_repository_id'), table_name='vector_indexes')
    op.drop_index(op.f('ix_vector_indexes_brain_id'), table_name='vector_indexes')
    op.drop_table('vector_indexes')
    op.drop_index(op.f('ix_knowledge_repositories_tenant_id'), table_name='knowledge_repositories')
    op.drop_index(op.f('ix_knowledge_repositories_organization_id'), table_name='knowledge_repositories')
    op.drop_index(op.f('ix_knowledge_repositories_brain_id'), table_name='knowledge_repositories')
    op.drop_table('knowledge_repositories')
    op.drop_index(op.f('ix_organization_brains_workspace_id'), table_name='organization_brains')
    op.drop_index(op.f('ix_organization_brains_tenant_id'), table_name='organization_brains')
    op.drop_index(op.f('ix_organization_brains_organization_id'), table_name='organization_brains')
    op.drop_table('organization_brains')
    op.drop_index(op.f('ix_audit_logs_tenant_id'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_sessions_token_hash'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_tenant_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_owner_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_organization_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_otp_codes_tenant_id'), table_name='otp_codes')
    op.drop_index(op.f('ix_otp_codes_phone'), table_name='otp_codes')
    op.drop_index(op.f('ix_otp_codes_organization_id'), table_name='otp_codes')
    op.drop_table('otp_codes')
    op.drop_index(op.f('ix_workspaces_tenant_id'), table_name='workspaces')
    op.drop_index(op.f('ix_workspaces_organization_id'), table_name='workspaces')
    op.drop_table('workspaces')
    op.drop_index('uq_owners_email_ci', table_name='owners', postgresql_where=sa.text('email IS NOT NULL'))
    op.drop_index(op.f('ix_owners_tenant_id'), table_name='owners')
    op.drop_index(op.f('ix_owners_phone'), table_name='owners')
    op.drop_index(op.f('ix_owners_organization_id'), table_name='owners')
    op.drop_table('owners')
    op.drop_index(op.f('ix_organizations_tenant_id'), table_name='organizations')
    op.drop_index(op.f('ix_organizations_status'), table_name='organizations')
    op.drop_index(op.f('ix_organizations_owner_onboard_token_hash'), table_name='organizations')
    op.drop_table('organizations')
    op.drop_index(op.f('ix_tenants_slug'), table_name='tenants')
    op.drop_table('tenants')
    # ### end Alembic commands ###
