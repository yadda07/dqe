"""
DQE Excel Manager
======================================================
Gestion des rapports Excel pour le plugin DQE Chargeur
"""

import os
import shutil
import tempfile
import time
from typing import Dict, List, Optional

import pandas as pd
from openpyxl import load_workbook

try:
    from .dqe_utils import _db_manager, _logger
    MODULES_AVAILABLE = True
except ImportError:
    _db_manager = _logger = None
    MODULES_AVAILABLE = False


class ExcelManager:
    @staticmethod
    def get_template_path(operation_type: str) -> str:
        """Retourne le chemin du template selon le type d'opération"""
        plugin_dir = os.path.dirname(__file__)
        template_files = {
            'PRO': 'template_dqe_pro.xlsx',
            'EXE': 'template_dqe_exe.xlsx', 
            'PGC': 'template_dqe_pgc.xlsx'
        }
        
        template_name = template_files.get(operation_type.upper(), 'template_dqe_pro.xlsx')
        template_path = os.path.join(plugin_dir, 'files', template_name)
        
        print(f"Template recherché pour {operation_type}: {template_path}")
        
        if not os.path.exists(template_path):
            print(f" Template non trouvé: {template_path}")
            # Fallback vers template PRO si le spécifique n'existe pas
            fallback_path = os.path.join(plugin_dir, 'files', 'template_dqe_pro.xlsx')
            if os.path.exists(fallback_path):
                print(f"Utilisation du template fallback: {fallback_path}")
                return fallback_path
            else:
                print(" Aucun template trouvé")
                return None
        
        return template_path
    
    @staticmethod
    def create_excel_report(results: List[Dict], sro: str, operation_type: str, troncon: str = None):
        """Génère le rapport Excel en utilisant le bon template"""
        if not results:
            return None
        
        try:
            print(f"\n=== Génération Excel {operation_type.upper()} ===")
            
            # Récupérer le template approprié
            template_path = ExcelManager.get_template_path(operation_type)
            if not template_path:
                print("⚠ Aucun template disponible, génération basique")
                return ExcelManager._create_basic_excel(results, sro, operation_type, troncon)
            
            # EXTRACTION DES DONNÉES REDEVANCE POUR PGC
            redevance_data = None
            if operation_type.upper() == 'PGC' and results:
                # Vérifier si le premier résultat contient des données redevance
                first_result = results[0]
                if hasattr(first_result, 'redevance_data') and first_result.redevance_data:
                    redevance_data = first_result.redevance_data
                    print(f"📊 Données REDEVANCE détectées: {len(redevance_data)} lignes")
                else:
                    print("📊 Aucune donnée REDEVANCE trouvée")
            
            # Préparation des données
            df = pd.DataFrame(results)
            
            # IMPORTANT: Préserver les IDs dans results pour le chargement des couches
            # Ne supprimer que du DataFrame Excel, pas de results original
            if 'ids' in df.columns:
                print(f"Conservation des IDs des câbles découpés pour {operation_type}")
                df = df.drop(columns=['ids'])  # Supprimer seulement du DataFrame Excel
            
            # Supprimer également la colonne redevance_data du DataFrame Excel si elle existe
            if 'redevance_data' in df.columns:
                df = df.drop(columns=['redevance_data'])
            
            if len(df.columns) >= 3:
                df.columns = ["Désignation", "Unité", "Quantité"]
                
                if "Quantité" in df.columns:
                    df["Quantité"] = pd.to_numeric(df["Quantité"], errors='coerce')
                    df["Quantité"] = df["Quantité"].round().fillna(0).astype(int)
            
            # Chemin de sortie
            temp_dir = tempfile.gettempdir()
            sro_safe = sro.replace('/', '_')
            
            if troncon:
                excel_path = os.path.join(temp_dir, f"dqe_{operation_type}_{sro_safe}_{troncon}_{int(time.time())}.xlsx")
            else:
                excel_path = os.path.join(temp_dir, f"dqe_{operation_type}_{sro_safe}_{int(time.time())}.xlsx")
            
            print(f"Fichier de sortie: {excel_path}")
            
            # Copier le template vers le fichier de sortie
            shutil.copy2(template_path, excel_path)
            print(f"Template copié vers: {excel_path}")
            
            # Charger le workbook et remplir les données
            workbook = load_workbook(excel_path)
            
            # Déterminer la feuille à utiliser
            sheet_name = f"DQE {operation_type.upper()}"
            
            # Essayer de trouver la bonne feuille
            target_sheet = None
            for sheet in workbook.sheetnames:
                if operation_type.upper() in sheet.upper():
                    target_sheet = workbook[sheet]
                    print(f"Feuille trouvée: {sheet}")
                    break
            
            if not target_sheet:
                # Prendre la première feuille par défaut
                target_sheet = workbook.active
                print(f"Feuille par défaut utilisée: {target_sheet.title}")
            
            # Remplir les données selon le type
            if operation_type.upper() == 'PGC':
                ExcelManager._fill_pgc_template(target_sheet, df, sro, troncon, workbook, redevance_data)
            else:
                ExcelManager._fill_standard_template(target_sheet, df, operation_type)
            
            # Sauvegarder et fermer
            workbook.save(excel_path)
            workbook.close()
            
            print(f" Rapport Excel généré: {excel_path}")
            
            # Ouvrir automatiquement
            ExcelManager._open_excel_file(excel_path)
            
            return excel_path
            
        except Exception as e:
            print(f" Erreur génération Excel: {str(e)}")
            import traceback
            print(traceback.format_exc())
            if _logger:
                _logger.error("Erreur génération Excel", exception=e)
            return None
    
    @staticmethod
    def _fill_standard_template(sheet, df, operation_type):
        """Remplit le template standard avec les données"""
        if df.empty:
            return
        
        if operation_type.upper() == 'EXE':
            # LOGIQUE EXE : Correspondance par index + alvéoles dynamiques
            return ExcelManager._fill_exe_template(sheet, df)
        else:
            # LOGIQUE PRO ULTRA-SIMPLIFIÉE : data[i] -> template ligne i+2
            # Ligne 1 template = header, ligne 2 template = première donnée
            updated_rows = []
            
            print(f"\n🔥 INDEXATION PRO DIRECTE : {len(df)} données à traiter")
            
            for i, (_, row) in enumerate(df.iterrows()):
                designation = row['Désignation']
                quantite = row['Quantité']
                
                # INDEXATION ULTRA-DIRECTE : data[i] -> template ligne i+2
                target_row = i + 2  # +2 car ligne 1 = header
                
                # Vérifier que la ligne existe dans le template
                if target_row <= sheet.max_row:
                    # Voir ce qu'il y a dans le template à cette ligne
                    template_cell_value = sheet.cell(row=target_row, column=1).value
                    
                    # Mettre à jour la quantité (colonne 3)
                    sheet.cell(row=target_row, column=3, value=quantite)
                    updated_rows.append(f"{designation} -> ligne {target_row}")
                    
                    print(f"  ✓ data[{i}] -> ligne {target_row}")
                    print(f"      pgAdmin: '{designation}' (Q: {quantite})")
                    print(f"      Template: '{template_cell_value}'")
                else:
                    print(f"  ✗ data[{i}] -> ligne {target_row} HORS LIMITE (max: {sheet.max_row})")
                    print(f"      pgAdmin: '{designation}' (Q: {quantite})")
            
            print(f"\nTemplate {operation_type.upper()} rempli: {len(updated_rows)} lignes")
            return updated_rows
    
    @staticmethod
    def _open_excel_file(excel_path: str):
        """Ouvre le fichier Excel avec l'application par défaut"""
        try:
            import subprocess
            import platform
            
            system = platform.system()
            if system == 'Windows':
                os.startfile(excel_path)
            elif system == 'Darwin':
                subprocess.call(['open', excel_path])
            else:
                subprocess.call(['xdg-open', excel_path])
                
        except Exception as e:
            print(f"Impossible d'ouvrir le fichier Excel: {e}")
            if _logger:
                _logger.warning("Impossible d'ouvrir automatiquement le fichier Excel", exception=e)
    
    @staticmethod
    def _find_template_row(sheet, designation: str, start_row: int = 1, end_row: int = None) -> Optional[int]:
        """Trouve la ligne correspondante dans le template avec correspondance intelligente pour BPE et câbles"""
        designation_lower = designation.lower().strip()
        
        print(f"🔍 Recherche template pour: '{designation}'")
        
        # Recherche avec logique spécialisée
        for row in range(start_row, min(end_row or sheet.max_row + 1, start_row + 200)):
            cell_value = sheet.cell(row=row, column=1).value
            if not cell_value:
                continue
            
            template_text = str(cell_value).lower().strip()
            
            # 1. Correspondance exacte (pour les éléments standards)
            if template_text == designation_lower:
                print(f"  ✓ Correspondance exacte trouvée ligne {row}: '{cell_value}'")
                return row
            
            # 2. Correspondance spécialisée pour les BPE
            if "bpe" in designation_lower and "bpe" in template_text:
                # Extraire le nombre de FO
                import re
                des_fo = re.search(r'(\d+)\s*fo', designation_lower)
                tem_fo = re.search(r'(\d+)\s*fo', template_text)
                
                if des_fo and tem_fo and des_fo.group(1) == tem_fo.group(1):
                    # Vérifier les mots-clés critiques pour différencier les types
                    critical_words = ['conduite', 'façade', 'aérien', 'immeuble']
                    matches_critical = True
                    
                    for word in critical_words:
                        des_has_word = word in designation_lower
                        tem_has_word = word in template_text
                        if des_has_word != tem_has_word:
                            matches_critical = False
                            break
                    
                    if matches_critical:
                        print(f"  ✓ Correspondance BPE {des_fo.group(1)} FO trouvée ligne {row}: '{cell_value}'")
                        return row
                    else:
                        print(f"  ⚠ BPE {des_fo.group(1)} FO trouvée ligne {row} mais mots-clés différents: '{cell_value}'")
            
            # 3. Correspondance spécialisée pour les câbles
            elif "câble" in designation_lower and "câble" in template_text:
                # Extraire nombre de FO
                import re
                des_fo = re.search(r'(\d+)\s*fo', designation_lower)
                tem_fo = re.search(r'(\d+)\s*fo', template_text)
                
                if des_fo and tem_fo and des_fo.group(1) == tem_fo.group(1):
                    # Vérifier les mots-clés critiques
                    critical_words = ['conduite', 'façade', 'aérien', 'immeuble']
                    matches_critical = True
                    
                    for word in critical_words:
                        des_has_word = word in designation_lower
                        tem_has_word = word in template_text
                        if des_has_word != tem_has_word:
                            matches_critical = False
                            break
                    
                    if matches_critical:
                        print(f"  ✓ Correspondance câble {des_fo.group(1)} FO trouvée ligne {row}: '{cell_value}'")
                        return row
                    else:
                        print(f"  ⚠ Câble {des_fo.group(1)} FO trouvée ligne {row} mais mots-clés différents: '{cell_value}'")
            
            # 4. Correspondance partielle avec similarité (fallback)
            elif len(designation_lower) > 5 and len(template_text) > 5:
                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, designation_lower, template_text).ratio()
                if similarity >= 0.85:  # 85% de similarité pour les autres éléments
                    print(f"  ✓ Correspondance par similarité ({similarity:.2f}) trouvée ligne {row}: '{cell_value}'")
                    return row
        
        print(f"  ❌ Aucune correspondance trouvée pour '{designation}'")
        return None

    @staticmethod
    def _fill_exe_template(sheet, df):
        """Remplit le template EXE (indexation directe + alvéoles dynamiques)"""
        if df.empty:
            return []
            
        updated_rows = []
        alveoles_data = []
        non_alveole_data = []
        
        print(f"\n🔥 INDEXATION EXE DIRECTE : {len(df)} données à traiter")
        
        # Première passe : séparer les alvéoles du reste
        for i, (_, row) in enumerate(df.iterrows()):
            designation = row['Désignation']
            quantite = row['Quantité']
            unite = row.get('Unité', 'ml')
            designation_lower = designation.lower()
            
            # Détection alvéoles
            is_alveole = False
            
            # Alvéoles réelles : PVC/PEHD avec détails techniques
            if any(keyword in designation_lower for keyword in ['pvc ', 'pehd ']):
                import re
                if re.search(r'pvc\s+\d+|pehd\s+\d+|\(.*fois.*\)', designation_lower):
                    # Exclure GC/TDR/RAD
                    if not any(exclude in designation_lower for exclude in ['gc -', 'tdr', 'rad', 'génie civil']):
                        is_alveole = True
            # Détection "alvéole" explicite
            elif any(keyword in designation_lower for keyword in ['alvéole', 'alveole']):
                if not any(exclude in designation_lower for exclude in ['gc -', 'tdr', 'rad', 'génie civil', 'fourniture des']):
                    is_alveole = True
            
            if is_alveole:
                alveoles_data.append({
                    'designation': designation,
                    'unite': unite,
                    'quantite': quantite
                })
                print(f"  → ALVÉOLE détectée: {designation}")
            # Ignorer aussi les titres de sections
            elif 'fourniture des alvéoles' in designation_lower:
                print(f"  → TITRE SECTION ignoré: {designation}")
            else:
                non_alveole_data.append({
                    'designation': designation,
                    'unite': unite,
                    'quantite': quantite,
                    'original_index': i
                })
        
        # Deuxième passe : INDEXATION DIRECTE pour les non-alvéoles
        print(f"  → Traitement de {len(non_alveole_data)} éléments non-alvéoles par indexation directe")
        
        for i, data in enumerate(non_alveole_data):
            designation = data['designation']
            quantite = data['quantite']
            
            # INDEXATION ULTRA-DIRECTE : data[i] -> template ligne i+2
            target_row = i + 2  # +2 car ligne 1 = header
            
            # Vérifier que la ligne existe dans le template
            if target_row <= sheet.max_row:
                # Voir ce qu'il y a dans le template à cette ligne
                template_cell_value = sheet.cell(row=target_row, column=1).value
                
                # Mettre à jour seulement la quantité (colonne 3)
                sheet.cell(row=target_row, column=3, value=quantite)
                updated_rows.append(f"{designation} -> ligne {target_row}")
                
                print(f"  ✓ data[{i}] -> ligne {target_row}")
                print(f"      pgAdmin: '{designation}' (Q: {quantite})")
                print(f"      Template: '{template_cell_value}'")
            else:
                print(f"  ✗ data[{i}] -> ligne {target_row} HORS LIMITE (max: {sheet.max_row})")
                print(f"      pgAdmin: '{designation}' (Q: {quantite})")
        
        # Troisième passe : Traitement dynamique des alvéoles
        if alveoles_data:
            print(f"  → Traitement de {len(alveoles_data)} alvéoles dynamiques...")
            # Trouver la section alvéoles
            alveoles_header_row = None
            for row in range(130, min(sheet.max_row + 10, 150)):
                cell_value = sheet.cell(row=row, column=1).value
                if cell_value and 'fourniture des alvéoles' in str(cell_value).lower():
                    alveoles_header_row = row
                    print(f"  → Section alvéoles trouvée ligne {row}")
                    break
            
            if alveoles_header_row:
                # Ajouter les alvéoles dynamiquement
                next_row = alveoles_header_row + 1
                for alv_data in alveoles_data:
                    # Trouver la prochaine ligne vide
                    while next_row <= sheet.max_row and sheet.cell(row=next_row, column=1).value:
                        next_row += 1
                    
                    sheet.cell(row=next_row, column=1, value=alv_data['designation'])
                    sheet.cell(row=next_row, column=2, value=alv_data['unite'])
                    sheet.cell(row=next_row, column=3, value=alv_data['quantite'])
                    updated_rows.append(f"ALVÉOLE {alv_data['designation']} -> ligne {next_row}")
                    print(f"  ✓ ALVÉOLE: {alv_data['designation']} -> ligne {next_row}")
                    next_row += 1
            else:
                print(f"  ⚠ Section alvéoles non trouvée, alvéoles ignorées")
        
        print(f"\nTemplate EXE rempli: {len(updated_rows)} lignes")
        return updated_rows

    @staticmethod
    def _fill_pgc_template(sheet, df: pd.DataFrame, sro: str, troncon: str, workbook=None, redevance_data: List[Dict] = None):
        """Remplit spécifiquement le template PGC avec indexation directe + gestion dynamique des alvéoles"""
        print(f"\n=== REMPLISSAGE TEMPLATE PGC (INDEXATION DIRECTE) ===")
        print(f"📊 Données: {len(df)} lignes")
        print(f"🏢 SRO: {sro}, 🔧 Tronçon: {troncon}")
        
        # 1. GÉRER LA LIGNE "Nom GC :" dynamiquement
        gc_row = None
        for row in range(1, min(20, sheet.max_row + 1)):
            cell_value = sheet.cell(row=row, column=1).value
            if cell_value and "Nom GC :" in str(cell_value):
                gc_row = row
                print(f"📍 Ligne 'Nom GC :' trouvée à la ligne {row}")
                break
        
        if gc_row:
            # Remplacer par le bon tronçon
            new_gc_text = f"Nom GC : {troncon}"
            sheet.cell(row=gc_row, column=1, value=new_gc_text)
            print(f"✅ Ligne GC mise à jour: '{new_gc_text}'")
        else:
            print("⚠️ Ligne 'Nom GC :' non trouvée dans le template")
        
        # 2. Rechercher la ligne d'en-tête "Désignation"
        header_row = None
        for row in range(1, min(50, sheet.max_row + 1)):
            cell_value = sheet.cell(row=row, column=1).value
            if cell_value and "Désignation" in str(cell_value):
                header_row = row
                print(f"📋 En-tête trouvé à la ligne {header_row}")
                break
        
        if not header_row:
            print("⚠️ En-tête 'Désignation' non trouvé, utilisation ligne 4")
            header_row = 4
        
        # 3. Trouver la section "Fourniture des Alvéoles" dans le template
        alveoles_section_row = None
        for row in range(header_row, sheet.max_row + 1):
            cell_value = sheet.cell(row=row, column=1).value
            if cell_value and "Fourniture des Alvéoles" in str(cell_value):
                alveoles_section_row = row
                print(f"🔧 Section alvéoles trouvée ligne {row}")
                break
        
        # 4. SÉPARER LES DONNÉES EN GROUPES
        alveoles_data = []
        static_data = []
        
        for index, row_data in df.iterrows():
            designation = str(row_data['Désignation']).strip()
            quantite = row_data['Quantité']
            unite = row_data.get('Unité', 'ml')
            
            # Ignorer les en-têtes et lignes spéciales
            if not designation or any(x in designation.lower() for x in [
                "nom gc", "désignation", "armoire de rue  -", "gc - tdr", 
                "pose de poteaux", "fourniture des alvéoles"
            ]):
                continue
            
            # Détecter les éléments d'alvéoles (PVC/PEHD)
            if any(x in designation.lower() for x in ["pvc ", "pehd"]):
                alveoles_data.append({
                    'index': index,
                    'designation': designation,
                    'unite': unite,
                    'quantite': quantite
                })
            else:
                static_data.append({
                    'index': index,
                    'designation': designation,
                    'unite': unite,
                    'quantite': quantite
                })
        
        print(f"📊 Répartition: {len(static_data)} éléments statiques, {len(alveoles_data)} alvéoles")
        
        # 5. PREMIÈRE PASSE : INDEXATION DIRECTE POUR ÉLÉMENTS STATIQUES
        print(f"\n🎯 === PHASE 1: INDEXATION DIRECTE STATIQUE ===")
        static_filled = 0
        
        for data in static_data:
            row_index = data['index']
            # INDEXATION DIRECTE : data[i] -> ligne i+header_row+1 (après l'en-tête)
            target_row = header_row + 1 + row_index
            
            print(f"📝 data[{row_index}] → ligne {target_row}: '{data['designation']}' = {data['quantite']}")
            
            # Vérifier que la ligne existe dans le template
            if target_row <= sheet.max_row:
                # Remplir les 3 colonnes
                if data['quantite'] > 0:  # Seulement si quantité > 0
                    sheet.cell(row=target_row, column=3, value=data['quantite'])  # Quantité
                    static_filled += 1
                    print(f"  ✅ Ligne {target_row} remplie")
                else:
                    print(f"  ⏭️ Ligne {target_row} ignorée (quantité = 0)")
            else:
                print(f"  ⚠️ Ligne {target_row} hors limites template (max: {sheet.max_row})")
        
        # 6. DEUXIÈME PASSE : GESTION DYNAMIQUE DES ALVÉOLES
        print(f"\n🔧 === PHASE 2: ALVÉOLES DYNAMIQUES ===")
        alveoles_filled = 0
        
        if alveoles_data and alveoles_section_row:
            # Commencer après la ligne de titre "Fourniture des Alvéoles"
            current_alveole_row = alveoles_section_row + 1
            
            for data in alveoles_data:
                if data['quantite'] > 0:  # Seulement si quantité > 0
                    print(f"🔧 Alvéole ligne {current_alveole_row}: '{data['designation']}' = {data['quantite']}")
                    
                    # Remplir les 3 colonnes
                    sheet.cell(row=current_alveole_row, column=1, value=data['designation'])
                    sheet.cell(row=current_alveole_row, column=2, value=data['unite'])
                    sheet.cell(row=current_alveole_row, column=3, value=data['quantite'])
                    
                    current_alveole_row += 1
                    alveoles_filled += 1
                    print(f"  ✅ Alvéole ajoutée")
                else:
                    print(f"  ⏭️ Alvéole '{data['designation']}' ignorée (quantité = 0)")
        else:
            print("⚠️ Section alvéoles non trouvée ou aucune donnée alvéole")
        
        # 7. TRAITEMENT DE LA FEUILLE REDEVANCE (si données présentes)
        if redevance_data and workbook:
            print(f"\n💰 === REMPLISSAGE FEUILLE REDEVANCE ===")
            ExcelManager._fill_redevance_sheet(workbook, redevance_data, sro, troncon)
        
        # 8. RÉSUMÉ FINAL
        print(f"\n✅ === RÉSUMÉ REMPLISSAGE PGC ===")
        print(f"📊 Éléments statiques remplis: {static_filled}/{len(static_data)}")
        print(f"🔧 Alvéoles remplies: {alveoles_filled}/{len(alveoles_data)}")
        print(f"💰 Redevance: {'✅ Traitée' if redevance_data else '❌ Aucune donnée'}")
        print(f"🎯 PRINCIPE: Indexation directe pour statique + dynamique pour alvéoles")
    
    @staticmethod
    def _find_next_section(sheet, current_section_row: int) -> int:
        """Trouve la ligne de fin de la section courante (début de la section suivante)"""
        # Chercher la prochaine ligne qui commence une nouvelle section
        for row in range(current_section_row + 1, min(current_section_row + 50, sheet.max_row + 1)):
            cell_value = sheet.cell(row=row, column=1).value
            if cell_value and isinstance(cell_value, str):
                # Si la ligne est en gras ou contient des mots-clés de section
                cell = sheet.cell(row=row, column=1)
                if (cell.font and cell.font.bold) or any(keyword in cell_value.lower() for keyword in [
                    "fourniture", "pose de", "armoire", "gc -", "transport", "distribution"
                ]):
                    return row - 1
        
        # Si pas trouvé, retourner une estimation
        return current_section_row + 20
    
    @staticmethod
    def _find_template_row(sheet, designation: str, start_row: int = 1, end_row: int = None) -> Optional[int]:
        """Trouve la ligne correspondante dans le template avec correspondance intelligente pour BPE et câbles"""
        designation_lower = designation.lower().strip()
        
        print(f"🔍 Recherche template pour: '{designation}'")
        
        # Recherche avec logique spécialisée
        for row in range(start_row, min(end_row or sheet.max_row + 1, start_row + 200)):
            cell_value = sheet.cell(row=row, column=1).value
            if not cell_value:
                continue
            
            template_text = str(cell_value).lower().strip()
            
            # 1. Correspondance exacte (pour les éléments standards)
            if template_text == designation_lower:
                print(f"  ✓ Correspondance exacte trouvée ligne {row}: '{cell_value}'")
                return row
            
            # 2. Correspondance spécialisée pour les BPE
            if "bpe" in designation_lower and "bpe" in template_text:
                # Extraire le nombre de FO
                import re
                des_fo = re.search(r'(\d+)\s*fo', designation_lower)
                tem_fo = re.search(r'(\d+)\s*fo', template_text)
                
                if des_fo and tem_fo and des_fo.group(1) == tem_fo.group(1):
                    # Vérifier les mots-clés critiques pour différencier les types
                    critical_words = ['conduite', 'façade', 'aérien', 'immeuble']
                    matches_critical = True
                    
                    for word in critical_words:
                        des_has_word = word in designation_lower
                        tem_has_word = word in template_text
                        if des_has_word != tem_has_word:
                            matches_critical = False
                            break
                    
                    if matches_critical:
                        print(f"  ✓ Correspondance BPE {des_fo.group(1)} FO trouvée ligne {row}: '{cell_value}'")
                        return row
                    else:
                        print(f"  ⚠ BPE {des_fo.group(1)} FO trouvée ligne {row} mais mots-clés différents: '{cell_value}'")
            
            # 3. Correspondance spécialisée pour les câbles
            elif "câble" in designation_lower and "câble" in template_text:
                # Extraire nombre de FO
                import re
                des_fo = re.search(r'(\d+)\s*fo', designation_lower)
                tem_fo = re.search(r'(\d+)\s*fo', template_text)
                
                if des_fo and tem_fo and des_fo.group(1) == tem_fo.group(1):
                    # Vérifier les mots-clés critiques
                    critical_words = ['conduite', 'façade', 'aérien', 'immeuble']
                    matches_critical = True
                    
                    for word in critical_words:
                        des_has_word = word in designation_lower
                        tem_has_word = word in template_text
                        if des_has_word != tem_has_word:
                            matches_critical = False
                            break
                    
                    if matches_critical:
                        print(f"  ✓ Correspondance câble {des_fo.group(1)} FO trouvée ligne {row}: '{cell_value}'")
                        return row
                    else:
                        print(f"  ⚠ Câble {des_fo.group(1)} FO trouvée ligne {row} mais mots-clés différents: '{cell_value}'")
            
            # 4. Correspondance partielle avec similarité (fallback)
            elif len(designation_lower) > 5 and len(template_text) > 5:
                designation_clean = ExcelManager._smart_match(designation)
                template_clean = ExcelManager._smart_match(str(cell_value))
                
                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, designation_clean, template_clean).ratio()
                if similarity >= 0.85:  # 85% de similarité pour les autres éléments
                    print(f"  ✓ Correspondance par similarité ({similarity:.2f}) trouvée ligne {row}: '{cell_value}'")
                    return row
        
        print(f"  ❌ Aucune correspondance trouvée pour '{designation}'")
        return None
    
    @staticmethod
    def _smart_match(text: str) -> str:
        """Nettoie et normalise le texte pour la correspondance intelligente"""
        import re
        
        if not text:
            return ""
        
        # Conversion en minuscules
        text = text.lower().strip()
        
        # Normalisation FO (avec/sans espace)
        text = re.sub(r'(\d+)\s*fo\b', r'\1 fo', text)
        
        # Gestion spéciale pour alvéoles (préserver les détails critiques)
        if any(keyword in text for keyword in ['pvc', 'pehd', 'alvéole', 'alveole']):
            # Pour les alvéoles, garder les parenthèses critiques 
            pass
        else:
            # Pour les autres, supprimer parenthèses et détails
            text = re.sub(r'\s*[\(\[\{].*$', '', text)
        
        # Normalisation "câble optique" -> "câble"
        text = re.sub(r'câble\s+optique', 'câble', text)
        
        # Suppression caractères de ponctuation parasites
        text = re.sub(r'[^\w\s\(\)\/\-\.]', '', text)
        
        # Normalisation espaces multiples
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    @staticmethod
    def _create_basic_excel(results: List[Dict], sro: str, operation_type: str, troncon: str = None):
        """Génération Excel basique si pas de template"""
        try:
            df = pd.DataFrame(results)
            
            if 'ids' in df.columns:
                df = df.drop(columns=['ids'])
            
            if len(df.columns) >= 3:
                df.columns = ["Désignation", "Unité", "Quantité"]
                
                if "Quantité" in df.columns:
                    df["Quantité"] = pd.to_numeric(df["Quantité"], errors='coerce')
                    df["Quantité"] = df["Quantité"].round().fillna(0).astype(int)
            
            temp_dir = tempfile.gettempdir()
            sro_safe = sro.replace('/', '_')
            
            if troncon:
                excel_path = os.path.join(temp_dir, f"dqe_{operation_type}_basic_{sro_safe}_{troncon}_{int(time.time())}.xlsx")
            else:
                excel_path = os.path.join(temp_dir, f"dqe_{operation_type}_basic_{sro_safe}_{int(time.time())}.xlsx")
            
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name=f'DQE {operation_type.upper()}', index=False)
            
            return excel_path
            
        except Exception as e:
            print(f"Erreur génération Excel basique: {e}")
            return None
    
    @staticmethod
    def _open_excel_file(excel_path: str):
        """Ouvre le fichier Excel avec l'application par défaut"""
        try:
            import subprocess
            import platform
            
            system = platform.system()
            if system == 'Windows':
                os.startfile(excel_path)
            elif system == 'Darwin':
                subprocess.call(['open', excel_path])
            else:
                subprocess.call(['xdg-open', excel_path])
                
        except Exception as e:
            print(f"Impossible d'ouvrir le fichier Excel: {e}")
            if _logger:
                _logger.warning("Impossible d'ouvrir automatiquement le fichier Excel", exception=e)

    @staticmethod
    def _fill_redevance_sheet(workbook, redevance_data: List[Dict], sro: str, troncon: str):
        """Remplit la feuille REDEVANCE avec les données de gc_exe.redevance_table"""
        print(f"Remplissage feuille REDEVANCE avec {len(redevance_data)} lignes")
        
        try:
            # Vérifier si la feuille REDEVANCE existe
            if 'REDEVANCE' in workbook.sheetnames:
                redevance_sheet = workbook['REDEVANCE']
                print("✓ Feuille REDEVANCE existante trouvée - préservation des en-têtes")
                
                # Déterminer la ligne de départ (préserver les en-têtes existants)
                start_row = 2  # Par défaut ligne 2 (ligne 1 = en-têtes)
                
                # Vérifier s'il y a des en-têtes existants en ligne 1
                existing_headers = []
                for col in range(1, redevance_sheet.max_column + 1):
                    cell_value = redevance_sheet.cell(row=1, column=col).value
                    if cell_value:
                        existing_headers.append(str(cell_value))
                
                if existing_headers:
                    print(f"✓ En-têtes existants trouvés: {existing_headers}")
                    print("✓ Les en-têtes seront préservés, remplissage des données seulement")
                else:
                    print("⚠ Aucun en-tête existant trouvé")
            
            else:
                print("⚠ Feuille REDEVANCE non trouvée dans le template, création d'une nouvelle feuille")
                redevance_sheet = workbook.create_sheet(title='REDEVANCE')
                start_row = 2  # Ligne 2 pour les données (ligne 1 pour en-têtes)
                existing_headers = []
            
            # Effacer seulement les données existantes (préserver la ligne 1 des en-têtes)
            max_row = redevance_sheet.max_row
            if max_row > 1:
                for row in redevance_sheet.iter_rows(min_row=2, max_row=max_row):
                    for cell in row:
                        cell.value = None
                print(f"✓ Données précédentes effacées (lignes 2-{max_row})")
            
            # Si pas de données, arrêter ici
            if not redevance_data:
                print("⚠ Aucune donnée redevance à remplir")
                return
            
            # Convertir en DataFrame pour faciliter le traitement
            df_redevance = pd.DataFrame(redevance_data)
            print(f"Colonnes des données: {list(df_redevance.columns)}")
            
            # Écrire les en-têtes SEULEMENT si la feuille est nouvelle ou vide
            if not existing_headers:
                print("✓ Écriture des en-têtes (feuille nouvelle ou vide)")
                for col_idx, column_name in enumerate(df_redevance.columns, start=1):
                    redevance_sheet.cell(row=1, column=col_idx, value=column_name)
            else:
                print("✓ En-têtes préservés (feuille existante)")
            
            # Écrire les données (toujours à partir de la ligne 2)
            for row_idx, (_, row_data) in enumerate(df_redevance.iterrows(), start=start_row):
                for col_idx, value in enumerate(row_data, start=1):
                    # Conversion des valeurs pour Excel
                    if pd.isna(value):
                        excel_value = None
                    elif isinstance(value, (int, float)):
                        excel_value = float(value) if value != int(value) else int(value)
                    else:
                        excel_value = str(value)
                    
                    redevance_sheet.cell(row=row_idx, column=col_idx, value=excel_value)
            
            # Ajuster la largeur des colonnes
            for column in redevance_sheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                
                adjusted_width = min(max_length + 2, 50)  # Max 50 caractères
                redevance_sheet.column_dimensions[column_letter].width = adjusted_width
            
            print(f"✓ Feuille REDEVANCE remplie avec {len(df_redevance)} lignes de données")
            print(f"✓ Colonnes: {', '.join(df_redevance.columns)}")
            
        except Exception as e:
            print(f"❌ Erreur lors du remplissage de la feuille REDEVANCE: {e}")
            if _logger:
                _logger.error("Erreur remplissage feuille REDEVANCE", exception=e)
