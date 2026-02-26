package com.nendo.argosy.util

import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineName
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlin.coroutines.CoroutineContext

private val loggingExceptionHandler = CoroutineExceptionHandler { context, throwable ->
    val name = context[CoroutineName]?.name ?: "unnamed"
    Logger.error("CoroutineScope", "Uncaught exception in scope '$name'", throwable)
}

fun SafeCoroutineScope(dispatcher: CoroutineContext, name: String = ""): CoroutineScope {
    val base = SupervisorJob() + dispatcher + loggingExceptionHandler
    return if (name.isNotEmpty()) {
        CoroutineScope(base + CoroutineName(name))
    } else {
        CoroutineScope(base)
    }
}
