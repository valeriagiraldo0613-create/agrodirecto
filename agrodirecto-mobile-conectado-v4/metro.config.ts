const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);

// Si necesitas agregar configuraciones personalizadas, hazlo respetando el objeto existente:
// config.transformer = {
//   ...config.transformer,
//   babelTransformerPath: require.resolve('tu-transformer-personalizado'),
// };

module.exports = config;