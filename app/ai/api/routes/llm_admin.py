import asyncio
import os
import string
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status

from app.ai.config import AIModuleConfig
from app.ai.deps import get_ai_config, reload_llm_client, get_llm_provider_repository
from app.ai.db.models import LLMProvider
from app.ai.db.repository import LLMProviderRepository
from app.auth.db.models import User
from app.auth.deps import get_current_admin_user
from app.core.logging import get_logger

# Import separated schemas
from app.ai.api.schemas.llm_admin import (
    ProviderConfigSchema,
    ProviderTestResult,
    DiagnosticsResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/llm", tags=["llm-admin"])


def obfuscate_api_key(key: Optional[str]) -> Optional[str]:
    """Obfuscate the API key or resolve and obfuscate the environment variable it references."""
    if not key:
        return None
    
    # If the key references an environment variable, check if it's set
    if key.startswith("${") and key.endswith("}"):
        env_var_name = key[2:-1]
        actual_val = os.getenv(env_var_name)
        if not actual_val:
            return f"{key} (Not Set)"
        # Show which environment variable is used and a secure preview of its value
        resolved_obfuscated = obfuscate_raw_value(actual_val)
        return f"{key} ({resolved_obfuscated})"

    return obfuscate_raw_value(key)


def obfuscate_raw_value(val: str) -> str:
    """Obfuscate a raw string value leaving only a secure prefix/suffix."""
    if not val:
        return ""
    if len(val) <= 8:
        return "****"
    return f"{val[:6]}...{val[-4:]}"


def is_key_obfuscated(key: Optional[str]) -> bool:
    """Check if the provided key string is in an obfuscated format."""
    if not key:
        return False
    return "..." in key or "*" in key or "Not Set" in key


@router.get(
    "/providers",
    response_model=List[ProviderConfigSchema],
    summary="Get configured LLM providers from database with obfuscated keys",
)
async def get_providers(
    current_user: User = Depends(get_current_admin_user),
    config: AIModuleConfig = Depends(get_ai_config),
    repository: LLMProviderRepository = Depends(get_llm_provider_repository),
):
    """
    Retrieve all LLM providers from MongoDB. API keys are returned
    in an obfuscated format to prevent secret exposure in the frontend.
    """
    try:
        providers = await repository.get_all_providers()
        
        result = []
        for p in providers:
            params = p.litellm_params.model_dump(exclude_none=True)
            if "api_key" in params:
                params["api_key"] = obfuscate_api_key(params["api_key"])
                
            result.append(
                ProviderConfigSchema(
                    id=str(p.id),
                    model_name=p.model_name,
                    litellm_params=params,
                    order=p.order,
                    is_active=p.is_active,
                )
            )
        return result
    except Exception as e:
        logger.error("admin_get_providers_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load LLM providers",
        )


@router.put(
    "/providers",
    summary="Update LLM providers configuration in database, preserving keys",
)
async def update_providers(
    providers_list: List[ProviderConfigSchema],
    current_user: User = Depends(get_current_admin_user),
    config: AIModuleConfig = Depends(get_ai_config),
    repository: LLMProviderRepository = Depends(get_llm_provider_repository),
):
    """
    Overwrite the LLMProvider collection. If incoming payload contains an obfuscated
    API key format, the original key value from the existing database record is preserved.
    """
    try:
        # Load existing providers from database to preserve keys
        existing_providers = await repository.get_all_providers()
        
        # Prepare list of documents to insert
        records_to_insert = []
        
        for new_p in providers_list:
            new_params = new_p.litellm_params.model_dump(exclude_none=True)
            new_key = new_params.get("api_key")
            
            if new_key and is_key_obfuscated(new_key):
                original_key = None
                
                # Match by provider ID first (stable across edits)
                if new_p.id:
                    for old_p in existing_providers:
                        if str(old_p.id) == new_p.id:
                            original_key = old_p.litellm_params.api_key
                            break
                
                # Fall back to matching by (model, api_base) tuple
                if not original_key:
                    for old_p in existing_providers:
                        if (old_p.litellm_params.model == new_params.get("model") and
                            old_p.litellm_params.api_base == new_params.get("api_base")):
                            original_key = old_p.litellm_params.api_key
                            break
                
                if original_key:
                    new_params["api_key"] = original_key
                else:
                    new_params.pop("api_key", None)
            
            # Construct Beanie Document
            doc = LLMProvider(
                model_name=new_p.model_name,
                litellm_params=new_params,
                order=new_p.order or 0,
                is_active=new_p.is_active
            )
            records_to_insert.append(doc)

        # Replace records in MongoDB
        await repository.replace_providers(records_to_insert)
        
        # Hot-reload in-memory cache
        await reload_llm_client(config, repository)
        
        logger.info("admin_update_providers_db_success", count=len(records_to_insert))
        return {"status": "success", "message": "Providers updated in database and hot-reloaded successfully."}
    except Exception as e:
        logger.error("admin_update_providers_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update LLM providers configuration",
        )


@router.post(
    "/reload",
    summary="Force reload LLM configuration from database",
)
async def force_reload_providers(
    current_user: User = Depends(get_current_admin_user),
    config: AIModuleConfig = Depends(get_ai_config),
    repository: LLMProviderRepository = Depends(get_llm_provider_repository),
):
    """
    Force clear the cache and reload configuration from MongoDB.
    """
    try:
        await reload_llm_client(config, repository)
        return {"status": "success", "message": "LLM client reloaded successfully."}
    except Exception as e:
        logger.error("admin_reload_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reload LLM client",
        )


async def _probe_provider(index: int, provider_dict: dict) -> ProviderTestResult:
    """Helper function to test a provider deployment directly using litellm.acompletion."""
    litellm_params = provider_dict.get("litellm_params", {})
    raw_model = litellm_params.get("model", "")
    api_base = litellm_params.get("api_base", "")
    
    # Resolve env variables
    model = string.Template(raw_model).safe_substitute(os.environ)
    api_base_resolved = string.Template(api_base).safe_substitute(os.environ) if api_base else None
    
    api_key_template = litellm_params.get("api_key", "")
    api_key = string.Template(api_key_template).safe_substitute(os.environ) if api_key_template else None
    
    if api_key and api_key.startswith("${") and api_key.endswith("}"):
        env_var_name = api_key[2:-1]
        api_key = os.getenv(env_var_name)

    import litellm

    test_messages = [{"role": "user", "content": "Respond with the word 'pong' and nothing else."}]
    start_time = time.time()
    
    try:
        kwargs = {
            "model": model,
            "messages": test_messages,
            "max_tokens": 5,
            "timeout": 12,
        }
        if api_base_resolved:
            kwargs["api_base"] = api_base_resolved
        if api_key:
            kwargs["api_key"] = api_key

        response = await litellm.acompletion(**kwargs)
        latency = time.time() - start_time
        content = response.choices[0].message.content
        response_text = (content or "").strip()
        
        if not response_text:
            return ProviderTestResult(
                index=index,
                model=model,
                status="FAILED",
                latency=latency,
                details="Error: Empty response received",
            )
            
        return ProviderTestResult(
            index=index,
            model=model,
            status="WORKING",
            latency=latency,
            details=f"Response: '{response_text}'",
        )
    except Exception as e:
        latency = time.time() - start_time
        error_msg = str(e).split("\n")[0]
        return ProviderTestResult(
            index=index,
            model=model,
            status="FAILED",
            latency=latency,
            details=f"Error: {error_msg}",
        )


@router.post(
    "/test",
    response_model=DiagnosticsResponse,
    summary="Test and diagnose all configured LLM providers in database",
)
async def test_providers(
    current_user: User = Depends(get_current_admin_user),
    config: AIModuleConfig = Depends(get_ai_config),
    repository: LLMProviderRepository = Depends(get_llm_provider_repository),
):
    """
    Probes all configured LLM providers in parallel, bypasses the router,
    and returns latency and success/failure statistics.
    """
    try:
        providers = await repository.get_all_providers()
    except Exception as e:
        logger.error("admin_test_providers_query_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query providers from database",
        )

    if not providers:
        return DiagnosticsResponse(total_models=0, working_models=0, failed_models=0, results=[])

    if config.use_mock_llm:
        results = [
            ProviderTestResult(
                index=i + 1,
                model=p.litellm_params.model if p.litellm_params and p.litellm_params.model else p.model_name,
                status="WORKING",
                latency=0.001,
                details="Response: 'pong' (mock)",
            )
            for i, p in enumerate(providers)
        ]
        return DiagnosticsResponse(
            total_models=len(results),
            working_models=len(results),
            failed_models=0,
            results=results,
        )

    # Convert to format suitable for probing
    provider_dicts = [p.to_litellm_dict() for p in providers]

    # Run probes concurrently
    tasks = [_probe_provider(i + 1, p) for i, p in enumerate(provider_dicts)]
    results = await asyncio.gather(*tasks)
    
    # Sort by original index
    results.sort(key=lambda r: r.index)
    
    working_count = sum(1 for r in results if r.status == "WORKING")
    failed_count = len(results) - working_count

    return DiagnosticsResponse(
        total_models=len(results),
        working_models=working_count,
        failed_models=failed_count,
        results=results,
    )
