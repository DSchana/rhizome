
from langchain.chat_models import BaseChatModel

def compute_chat_model_max_tokens(chat_model: BaseChatModel):
    """Attempt to compute the maximum token count for a given chat model, returning None if
    the necessary information can't be acquired from the chat model profile.
    
    Chat model profiles are a beta feature in langchain, so this method has a number of
    passthroughs for potentially missing/incomplete info.
    """
    if not hasattr(chat_model, "profile"):
        return None
    
    profile = chat_model.profile
    if profile is None:
        return None
    
    max_tokens = profile.get("max_input_tokens", None)
    if max_tokens is None:
        return None
    
    max_tokens += profile.get("max_output_tokens", 0)
    return max_tokens