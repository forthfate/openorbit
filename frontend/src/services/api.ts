import { resolveLocale } from "../locales";

const requestLocale = () => resolveLocale(localStorage.getItem("orbit.locale"));

export async function api<T>(path:string, method='GET', body?:unknown):Promise<T>{const response=await fetch(path,{method,headers:{'Content-Type':'application/json','Accept-Language':requestLocale()},body:body?JSON.stringify(body):undefined}),contentType=response.headers.get('content-type')??'';if(!response.ok)throw new Error(await response.text());if(!contentType.includes('application/json'))throw new Error(`API returned ${contentType||'a non-JSON response'} for ${path}. Restart the OpenOrbit server and try again.`);return response.json()}

export async function upload<T>(path:string,file:File):Promise<T>{const form=new FormData();form.append('file',file);const response=await fetch(path,{method:'POST',headers:{'Accept-Language':requestLocale()},body:form}),contentType=response.headers.get('content-type')??'';if(!response.ok)throw new Error(await response.text());if(!contentType.includes('application/json'))throw new Error(`API returned ${contentType||'a non-JSON response'} for ${path}. Restart the OpenOrbit server and try again.`);return response.json()}
