import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react';

type FieldProps = {
  id: string;
  label: string;
  multiline?: boolean;
  rows?: number;
} & Omit<InputHTMLAttributes<HTMLInputElement> & TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'>;

export default function Field({ id, label, multiline = false, rows = 3, ...props }: FieldProps) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {multiline ? (
        <textarea id={id} rows={rows} {...(props as TextareaHTMLAttributes<HTMLTextAreaElement>)} />
      ) : (
        <input id={id} {...(props as InputHTMLAttributes<HTMLInputElement>)} />
      )}
    </div>
  );
}
