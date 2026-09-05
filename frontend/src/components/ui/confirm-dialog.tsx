import { Modal } from './modal'

export function ConfirmDialog({open,title,description,cancelLabel,confirmLabel,onCancel,onConfirm}:{open:boolean;title:string;description:string;cancelLabel:string;confirmLabel:string;onCancel:()=>void;onConfirm:()=>void}){
  return <Modal open={open} title={title} onClose={onCancel} className="modal--confirm"><p className="confirm-description">{description}</p><div className="modal-actions"><button className="ghost" onClick={onCancel}>{cancelLabel}</button><button className="reject" onClick={onConfirm}>{confirmLabel}</button></div></Modal>
}
