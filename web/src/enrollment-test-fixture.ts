import { BAA, ENROLLMENT_CONTRACT, type EnrollmentConfig, type EnrollmentDocument, type EnrollmentStatus } from './enrollment-contract';
export const enrollmentConfig = ():EnrollmentConfig => ({contract_version:ENROLLMENT_CONTRACT,enabled:true,data_mode:'synthetic',
  auth_configured:true,clerk_publishable_key:'pk_test_invented',auth_methods:['google','microsoft','password'],billing_configured:true,
  activation_available:false,production_qualified:false,blockers:[],allowed_workspace_origins:['https://workspace.example.invalid'],baa:BAA,
  pricing:{currency:'usd',interval:'month',first_human_cents:30000,additional_human_cents:10000,max_self_serve_humans:10,trial_days:14,
    seat_policy:'All humans consume a purchased seat; paused users retain their seat until removed.'}});
export const enrollmentDocument = ():EnrollmentDocument => ({...BAA,html:'<article><h1>CN-BAA-CUST-CW v2.3</h1><p>Invented render fixture only; this is not a signed agreement.</p></article>'});
export const enrollmentStatus = (stage:EnrollmentStatus['stage']='account',revision=0,seats=1):EnrollmentStatus => ({contract_version:ENROLLMENT_CONTRACT,stage,revision,
  profile:stage==='account'?null:{display_name:'Invented Owner',title:'Owner',email:'owner@example.invalid'},
  practice:['account','practice'].includes(stage)?null:{id:'10000000-0000-4000-8000-000000000001',legal_name:'Invented Legal Practice',display_name:'Invented Practice',
    address_line1:'123 Invented Street',address_line2:'',city:'Invented City',region:'NY',postal_code:'10001',country:'US',administrative_email:'office@example.invalid',human_seats:seats,role:'owner',covered_entity:true,can_sign:true},
  agreement:['account','practice'].includes(stage)?null:{accepted:stage!=='agreement',doc_id:BAA.doc_id,version:BAA.version,sha256:BAA.sha256,receipt_id:stage==='agreement'?null:'10000000-0000-4000-8000-000000000002'},
  quote:['account','practice'].includes(stage)?null:{currency:'usd',interval:'month',human_seats:seats,monthly_total_cents:seats<=10?30000+(seats-1)*10000:null,due_today_cents:0,trial_days:14,self_serve:seats<=10},
  billing:{status:stage==='ready'?'trialing':'none',trial_ends_at:stage==='ready'?'2026-11-15T12:00:00Z':null,first_charge_at:stage==='ready'?'2026-11-15T12:00:00Z':null,cancel_at_period_end:false,payment_action_required:false},
  workspace:{status:stage==='ready'?'ready':'pending',url:stage==='ready'?'https://workspace.example.invalid/':null,organization_id:stage==='ready'?'org_invented':null,box_id:stage==='ready'?'10000000-0000-4000-8000-000000000003':null},action_required:null});
