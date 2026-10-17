import {teamAddress,teamUuid} from './team-setup-request';
export type WorkspaceRoute={page:'home'|'visits'|'notebook'|'settings'|'work';workspaceId?:string;helper?:string;material?:string};
const materials=['Notebook','Conversation','Sources','Review','Work'];
export function readWorkspaceRoute(hash:string):WorkspaceRoute|null{
  const match=/^#cosmas\/(home|visits|notebook|settings|work)(?:\/([^?]+))?(?:\?(.*))?$/.exec(hash);
  if(!match)return null;
  const page=match[1] as WorkspaceRoute['page'],workspaceId=match[2],query=new URLSearchParams(match[3]??'');
  if(page==='notebook'?!teamUuid(workspaceId):workspaceId!==undefined)return null;
  const helper=query.get('helper'),material=query.get('material');
  if(helper!==null&&!teamAddress(helper)||material!==null&&!materials.includes(material))return null;
  return {page,...(workspaceId?{workspaceId}:{}),...(helper?{helper}:{}),...(material?{material}:{})};
}
export function workspaceRouteHash(route:WorkspaceRoute){
  const query=new URLSearchParams();
  if(route.page==='notebook'){if(route.helper)query.set('helper',route.helper);if(route.material)query.set('material',route.material);}
  return `#cosmas/${route.page}${route.page==='notebook'?'/'+route.workspaceId:''}${query.size?'?'+query:''}`;
}
