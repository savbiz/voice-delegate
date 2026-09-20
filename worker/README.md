# Worker — M2

Implement a LangGraph agent behind the internal async `delegate_task(goal, context)` boundary. Include timeout, cancellation, bounded steps and results, and an offline fake model. Select the worker model independently of the voice provider. No LangGraph worker is implemented or installed in M1.

Public reference for M2: https://docs.langchain.com/oss/python/langgraph/overview
