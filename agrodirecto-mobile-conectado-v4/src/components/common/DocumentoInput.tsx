import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import colors from '../../theme/colors';
import InputField from './InputField';

// Códigos que acepta el backend (tabla tipos_documento).
export const TIPOS_DOCUMENTO = [
  { codigo: 'CC', nombre: 'Cédula' },
  { codigo: 'NIT', nombre: 'NIT' },
  { codigo: 'CE', nombre: 'C. Extranjería' },
  { codigo: 'PP', nombre: 'Pasaporte' },
];

interface Props {
  tipo: string;
  numero: string;
  onChangeTipo: (codigo: string) => void;
  onChangeNumero: (numero: string) => void;
}

export default function DocumentoInput({ tipo, numero, onChangeTipo, onChangeNumero }: Props) {
  return (
    <View>
      <Text style={styles.label}>Tipo de Documento *</Text>
      <View style={styles.chips}>
        {TIPOS_DOCUMENTO.map((t) => {
          const activo = tipo === t.codigo;
          return (
            <TouchableOpacity
              key={t.codigo}
              style={[styles.chip, activo && styles.chipActivo]}
              onPress={() => onChangeTipo(t.codigo)}
              activeOpacity={0.8}
            >
              <Text style={[styles.chipTexto, activo && styles.chipTextoActivo]}>{t.codigo}</Text>
            </TouchableOpacity>
          );
        })}
      </View>
      <InputField
        label="Número de Documento *"
        placeholder={tipo === 'NIT' ? 'Ej: 900123456-1' : 'Ej: 1010101010'}
        keyboardType={tipo === 'PP' ? 'default' : 'numbers-and-punctuation'}
        autoCapitalize="characters"
        value={numero}
        onChangeText={onChangeNumero}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  label: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
    marginBottom: 6,
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 12,
  },
  chip: {
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipActivo: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  chipTexto: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  chipTextoActivo: {
    color: colors.textInverted,
  },
});
