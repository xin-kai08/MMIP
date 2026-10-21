import type {Answer} from './api'

export const fixedResidual=(waste:string|null)=>waste==='general'||waste==='food_waste'
export const compatibleAnswer=(a:Answer)=>!fixedResidual(a.waste)||a.residual===null||a.residual==='not_assessable'

// Only explicit interaction changes the draft; loading historical answers never
// normalizes them or writes the database. Confirmation is always a separate act.
export function changeWaste(answer:Answer,waste:string|null):Answer{
 if(waste===answer.waste)return answer
 let residual=answer.residual
 if(!waste)residual=null
 else if(fixedResidual(waste))residual='not_assessable'
 else if(fixedResidual(answer.waste))residual=null
 return {...answer,waste,waste_confirmed:false,residual,
  residual_confirmed:!fixedResidual(waste)&&residual===answer.residual?answer.residual_confirmed:false}
}

export function changeResidual(answer:Answer,residual:string|null):Answer{
 return residual===answer.residual?answer:{...answer,residual,residual_confirmed:false}
}
