# Copyright 2026 Mahendra GURAV
import pytest
from unittest.mock import patch
from core_platform.app.common.phone_validator import is_valid_phone_number, normalize_phone_number
from apps.temperature_marker.database.db_service import DatabaseService
from apps.temperature_marker.knowledge_graph.service import KnowledgeGraphService

class TestPhoneNormalization:
    def test_ten_digit_indian_number(self):
        assert normalize_phone_number('8087545430') == '+918087545430'
        assert normalize_phone_number('9822012345') == '+919822012345'

    def test_twelve_digit_indian_number_without_plus(self):
        assert normalize_phone_number('918087545430') == '+918087545430'

    def test_eleven_digit_trunk_zero(self):
        assert normalize_phone_number('08087545430') == '+918087545430'

    def test_formatted_with_spaces_and_hyphens(self):
        assert normalize_phone_number('+91 80875-45430') == '+918087545430'
        assert normalize_phone_number(' (808) 754-5430 ') == '+918087545430'

    def test_international_number_preserved(self):
        assert normalize_phone_number('+14155552671') == '+14155552671'
        assert normalize_phone_number('+447911123456') == '+447911123456'

    def test_invalid_phone_raises(self):
        with pytest.raises(ValueError):
            normalize_phone_number('')
        with pytest.raises(ValueError):
            normalize_phone_number('abc')
        with pytest.raises(ValueError):
            normalize_phone_number('123')

    def test_is_valid_helper(self):
        assert is_valid_phone_number('8087545430') is True
        assert is_valid_phone_number('+918087545430') is True
        assert is_valid_phone_number('invalid') is False

class TestOperatorManagementDB:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        db_path = tmp_path / 'test_mgmt.db'
        self.db = DatabaseService(db_url=f'sqlite:///{db_path}')

    def test_update_employee_fields(self):
        emp = self.db.register_employee(
            emp_code='EMP-9001',
            full_name='Original Name',
            phone_number='+918087000001',
            assigned_kiosk_id='NODE-PUNE-01',
            status='PENDING_PHOTO',
        )
        assert emp.full_name == 'Original Name'

        updated = self.db.update_employee(
            emp_code='EMP-9001',
            full_name='Updated Name',
            phone_number='+918087000002',
            assigned_kiosk_id='NODE-PUNE-02',
            reporting_manager_emp_code='MGR-001',
            status='ACTIVE',
        )
        assert updated is not None
        assert updated.full_name == 'Updated Name'
        assert updated.phone_number == '+918087000002'
        assert updated.assigned_kiosk_id == 'NODE-PUNE-02'
        assert updated.reporting_manager_emp_code == 'MGR-001'
        assert updated.status == 'ACTIVE'

    def test_update_nonexistent_employee(self):
        assert self.db.update_employee(emp_code='EMP-NONEXISTENT', full_name='Ghost') is None

class TestKioskGPSCalibration:
    def test_update_kiosk_coordinates(self, tmp_path):
        roster_file = tmp_path / 'roster.json'
        kg = KnowledgeGraphService(roster_path=roster_file)
        kg.add_kiosk(
            kiosk_id='NODE-TEST-01',
            site_name='Test Site',
            city='Pune',
            latitude=18.5204,
            longitude=73.8567,
            radius_meters=100.0,
        )
        ok = kg.update_kiosk_coordinates(
            kiosk_id='NODE-TEST-01',
            latitude=18.5500,
            longitude=73.9000,
            radius_meters=150.0,
        )
        assert ok is True
        coords = kg.get_kiosk_coordinates('NODE-TEST-01')
        assert coords is not None
        assert abs(coords[0] - 18.5500) < 1e-4
        assert abs(coords[1] - 73.9000) < 1e-4
        assert coords[2] == 150.0

@pytest.mark.asyncio
class TestUnregisteredSenderIngressGuard:
    async def test_unregistered_sender_greeting_blocked(self):
        from core_platform.app.ingress.whatsapp_router import dispatch_whatsapp_payload
        payload = {
            'entry': [{
                'changes': [{
                    'value': {
                        'messages': [{
                            'from': '919999999999',
                            'type': 'text',
                            'text': {'body': 'hi'},
                        }]
                    }
                }]
            }]
        }
        with patch('core_platform.app.ingress.whatsapp_router.settings') as mock_settings:
            mock_settings.WHATSAPP_ACCESS_TOKEN = ''
            mock_settings.WHATSAPP_PHONE_NUMBER_ID = ''
            mock_settings.ORCHESTRATOR_BASE_URL = 'http://localhost:8002'
            mock_settings.KIOSK_ID = 'NODE-PUNE-01'
            result = await dispatch_whatsapp_payload(payload)
            assert result['status'] in ('EVENT_RECEIVED', 'UNREGISTERED_USER')
            reply = result['reply_message']
            assert 'not registered' in reply.lower()
            assert '1-click' not in reply.lower()
            assert '/loc?session=' not in reply
            assert 'Shift Attendance: PENDING' not in reply
