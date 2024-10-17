import React from 'react';

const BooleanInput = ({ label, value, onChange }) => (
  <div className="my-4">
    <label className="font-semibold mb-2 block">{label}</label>
    <input
      type="checkbox"
      checked={value}
      onChange={onChange}
      className="mr-2"
    />
    {label}
  </div>
);

export default BooleanInput;