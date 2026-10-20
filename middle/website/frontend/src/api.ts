import config from '../../config.json'
export const API = config.api_prefix
export const waste:Record<string,string>={general:'一般垃圾',glass:'玻璃',food_waste:'廚餘',other_recycling:'其他回收'}
export const residual:Record<string,string>={none:'無殘留',food:'食物殘留',liquid:'液體殘留',not_assessable:'不適用／無法判斷'}
export const statuses:Record<string,string>={queued:'排隊中',processing:'辨識中',completed:'已完成',failed:'失敗'}
export type Answer={waste:string|null,residual:string|null,waste_confirmed:boolean,residual_confirmed:boolean}
export const emptyAnswer=():Answer=>({waste:null,residual:null,waste_confirmed:false,residual_confirmed:false})
export type Annotation={id:number,source:string,waste_label:string|null,residual_label:string|null,waste_confirmed:number,residual_confirmed:number,created_at:string,annotator_id:string}
export type Prediction={waste_label:string,residual_label:string,waste_confidence:number,residual_confidence:number,waste_low:number,residual_low:number,threshold:number,model_version:string,elapsed_ms:number}
export type ImageRow={id:string,original_name:string,status:string,error:string|null,has_image:boolean,prediction:Prediction|null,annotations:Annotation[]}
export type Batch={id:string,mode:string,status:string,created_at:string,images:ImageRow[],finished_count:number}
export type Health={model_ready:boolean,model_error:string|null,model_version:string|null,model:{threshold?:number},limits:{max_files:number,max_file_bytes:number,max_pixels:number,formats:string[]}}
export async function request<T>(path:string,init?:RequestInit):Promise<T>{
 const response=await fetch(API+path,init)
 if(!response.ok){let message=`請求失敗 (${response.status})`;try{const body=await response.json();message=typeof body.detail==='string'?body.detail:JSON.stringify(body.detail)}catch{}throw new Error(message)}
 return response.json()
}
export const json=(body:unknown)=>({headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
export const query=(user:string)=>`user_id=${encodeURIComponent(user)}`
export const fileUrl=(id:string,user:string)=>`${API}/images/${encodeURIComponent(id)}/file?${query(user)}`
export const time=(date:string)=>new Date(date).toLocaleString('zh-TW',{hour12:false})
