using UnityEditor;

namespace Manual2AR.Editor {
 // Only local experimental meshes. No package, assembly or upstream script import.
 public sealed class GuidanceLocalAssetImport:AssetPostprocessor {
  void OnPreprocessModel(){
   if(!assetPath.StartsWith("Assets/Manual2AR/Resources/GuidanceLocal/"))return;
   var importer=(ModelImporter)assetImporter;
   importer.isReadable=true;importer.importAnimation=false;
   importer.importCameras=false;importer.importLights=false;
   importer.materialImportMode=ModelImporterMaterialImportMode.None;
  }
 }
}
