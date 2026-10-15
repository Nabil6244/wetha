export class ApiError extends Error {
  constructor(message:string, public status=0){super(message);this.name='ApiError';}
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const read=body===undefined;
  for(let attempt=0;;attempt++){
    try{
      const response = await fetch('/api' + path, {
        method: read ? 'GET' : 'POST',
        headers: read ? {} : {'Content-Type': 'application/json'},
        body: read ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(read?45000:90000),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        const detail=result.detail;
        const message=typeof detail==='string'?detail:Array.isArray(detail)?detail.map((item:{loc?:unknown[];msg?:string})=>`${item.loc?.filter(x=>x!=='body').join(' · ')||'Input'}: ${item.msg||'Check this value'}`).slice(0,4).join('. '):`The local service could not complete this request (${response.status}). Try again.`;
        throw new ApiError(message,response.status);
      }
      return await response.json();
    }catch(error){
      // Retry reads only. Repeating a POST after a lost response could duplicate saved work.
      if(read&&attempt===0&&(!(error instanceof ApiError)||[502,503,504].includes(error.status))){
        await new Promise(resolve=>setTimeout(resolve,750));continue;
      }
      if(error instanceof ApiError)throw error;
      if(error instanceof Error&&['TimeoutError','AbortError'].includes(error.name))throw new ApiError('The local service is taking longer than expected. Your work may still be running; refresh its status before starting again.');
      throw new ApiError('Connection to the local service was interrupted. Your saved work is preserved. Retry after it reconnects.');
    }
  }
}
