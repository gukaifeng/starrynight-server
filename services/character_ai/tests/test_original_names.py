import unittest
from services.character_ai.profiles import PROFILES, ORIGINAL_NAMES
from services.character_ai.public_profiles import public_profile
from services.character_ai.prompts import PLANNER
from scripts.prepare_character_openings import compile_catalog

class OriginalNamesTests(unittest.TestCase):
    def test_identity_is_authoritative_after_scenario_merge(self):
        for role, (old, name) in ORIGINAL_NAMES.items():
            self.assertEqual(PROFILES[role]['name'], name)
            self.assertEqual(public_profile(role)['name'], name)
            self.assertNotIn(old, public_profile(role)['story'])
            self.assertEqual(PROFILES[role]['profile_revision'], '2026-10-02-original-names-v1')
        self.assertIn('character_profile.name', PLANNER)

    def test_new_openings_and_legacy_audio_have_distinct_ids(self):
        roles={c['characterID']:c for c in compile_catalog()['characters']}
        for role in ('anime-chiffon','anime-ichigo','anime-mafuyu','anime-plum'):
            old,name=ORIGINAL_NAMES[role]
            self.assertEqual(len(roles[role]['variants']),3)
            for v in roles[role]['variants']:
                self.assertIn(name,v['text']);self.assertNotIn(old,v['text'])
                self.assertIn('-v3-',v['id'])
            historical=[v for v in roles[role]['legacyVariants'] if '-v2-' in v['id']]
            self.assertEqual(len(historical),3)
            self.assertTrue(all(old in v['text'] for v in historical))
        self.assertTrue(all('-v2-' in v['id'] for v in roles['anime-lime']['variants']))

if __name__=='__main__': unittest.main()
