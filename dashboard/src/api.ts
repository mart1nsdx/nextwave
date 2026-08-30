import type {
  CallEvidence,
  CallSummary,
  CommandResult,
  OperationSummary,
  OperationConfiguration,
  OperationWorkspace,
} from './types'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })

  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null)
    const detail = typeof payload === 'object' && payload !== null && 'detail' in payload
      ? (payload as { detail?: unknown }).detail
      : null
    throw new Error(typeof detail === 'string' ? detail : `Dashboard API failed with ${response.status}.`)
  }
  return response.json() as Promise<T>
}

export const controlTowerApi = {
  listOperations: (): Promise<OperationSummary[]> => request('/operations'),
  getWorkspace: (operationId: string): Promise<OperationWorkspace> =>
    request(`/operations/${operationId}/workspace`),
  getConfiguration: (operationId: string): Promise<OperationConfiguration> =>
    request(`/operations/${operationId}/configuration`),
  listCalls: (): Promise<CallSummary[]> => request('/calls'),
  getCalls: (operationId: string): Promise<CallSummary[]> =>
    request(`/operations/${operationId}/calls`),
  getEvidence: (callId: string): Promise<CallEvidence> => request(`/calls/${callId}/evidence`),
  activateRfq: (
    operationId: string,
    rfqId: string,
    carrierIds: string[],
    idempotencyKey: string,
  ): Promise<CommandResult> =>
    request(`/operations/${operationId}/rfqs/${rfqId}/activate`, {
      method: 'POST',
      body: JSON.stringify({ carrier_ids: carrierIds, idempotency_key: idempotencyKey }),
    }),
  requestAward: (
    operationId: string,
    rfqId: string,
    offerId: string,
    idempotencyKey: string,
  ): Promise<CommandResult> =>
    request(`/operations/${operationId}/rfqs/${rfqId}/request-award`, {
      method: 'POST',
      body: JSON.stringify({ offer_id: offerId, idempotency_key: idempotencyKey }),
    }),
}
