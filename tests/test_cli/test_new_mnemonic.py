import asyncio
import os
from pathlib import Path
import json

import pytest
from py_ecc.bls import G2ProofOfPossession as bls
from click.testing import CliRunner

from eth2deposit.cli import new_mnemonic
from eth2deposit.deposit import cli
from eth2deposit.key_handling.key_derivation.path import mnemonic_and_path_to_key
from eth2deposit.utils.constants import DEFAULT_VALIDATOR_KEYS_FOLDER_NAME
from eth2deposit.utils.crypto import SHA256
from .helpers import clean_key_folder, get_uuid


def test_new_mnemonic(monkeypatch) -> None:
    mock_mnemonic = "legal winner thank year wave sausage worth useful legal winner thank yellow"

    # monkeypatch get_mnemonic
    def mock_get_mnemonic(language, words_path, entropy=None) -> str:
        return mock_mnemonic

    monkeypatch.setattr(new_mnemonic, "get_mnemonic", mock_get_mnemonic)

    # Prepare folder
    my_folder_path = os.path.join(os.getcwd(), 'TESTING_TEMP_FOLDER')
    clean_key_folder(my_folder_path)
    if not os.path.exists(my_folder_path):
        os.mkdir(my_folder_path)

    runner = CliRunner()
    inputs = ['english', '1', 'mainnet', 'MyPassword', 'MyPassword', mock_mnemonic]
    data = '\n'.join(inputs)
    result = runner.invoke(cli, ['new-mnemonic', '--folder', my_folder_path], input=data)
    assert result.exit_code == 0

    # Check files
    validator_keys_folder_path = os.path.join(my_folder_path, DEFAULT_VALIDATOR_KEYS_FOLDER_NAME)
    _, _, files = next(os.walk(validator_keys_folder_path))
    key_files = sorted([key_file for key_file in files if key_file.startswith('keystore')])
    deposit_data_file = [data_file for data_file in files if data_file.startswith('deposit_data')][0]

    all_uuid = [
        get_uuid(validator_keys_folder_path + '/' + key_file)
        for key_file in key_files
    ]
    assert len(set(all_uuid)) == 1

    # Verify keys
    purpose = '12381'
    coin_type = '3600'
    account = 0
    withdrawal_key_path = f'm/{purpose}/{coin_type}/{account}/0'
    signing_key_path = f'{withdrawal_key_path}/0'
    withdrawal_sk = mnemonic_and_path_to_key(mnemonic=mock_mnemonic, path=withdrawal_key_path, password='')
    signing_sk = mnemonic_and_path_to_key(mnemonic=mock_mnemonic, path=signing_key_path, password='')

    with open(Path(validator_keys_folder_path + '/' + deposit_data_file)) as f:
        deposit_data_list = json.load(f)
    deposit_data = deposit_data_list[0]
    assert bls.SkToPk(signing_sk).hex() == deposit_data['pubkey']
    assert (b'\x00' + SHA256(bls.SkToPk(withdrawal_sk))[1:]).hex() == deposit_data['withdrawal_credentials']

    # Clean up
    clean_key_folder(my_folder_path)


@pytest.mark.asyncio
async def test_script() -> None:
    my_folder_path = os.path.join(os.getcwd(), 'TESTING_TEMP_FOLDER')
    if not os.path.exists(my_folder_path):
        os.mkdir(my_folder_path)

    if os.name == 'nt':  # Windows
        run_script_cmd = 'sh deposit.sh'
    else:  # Mac or Linux
        run_script_cmd = './deposit.sh'

    install_cmd = run_script_cmd + ' install'
    proc = await asyncio.create_subprocess_shell(
        install_cmd,
    )
    await proc.wait()

    cmd_args = [
        run_script_cmd + ' new-mnemonic',
        '--num_validators', '5',
        '--mnemonic_language', 'english',
        '--chain', 'mainnet',
        '--keystore_password', 'MyPassword',
        '--folder', my_folder_path,
    ]
    proc = await asyncio.create_subprocess_shell(
        ' '.join(cmd_args),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )

    seed_phrase = ''
    parsing = False
    async for out in proc.stdout:
        output = out.decode('utf-8').rstrip()
        if output.startswith("This is your seed phrase."):
            parsing = True
        elif output.startswith("Please type your mnemonic"):
            parsing = False
        elif parsing:
            seed_phrase += output
            if len(seed_phrase) > 0:
                encoded_phrase = seed_phrase.encode()
                proc.stdin.write(encoded_phrase)
                proc.stdin.write(b'\n')

    assert len(seed_phrase) > 0

    # Check files
    validator_keys_folder_path = os.path.join(my_folder_path, DEFAULT_VALIDATOR_KEYS_FOLDER_NAME)
    _, _, key_files = next(os.walk(validator_keys_folder_path))

    all_uuid = [
        get_uuid(validator_keys_folder_path + '/' + key_file)
        for key_file in key_files
        if key_file.startswith('keystore')
    ]
    assert len(set(all_uuid)) == 5

    # Clean up
    clean_key_folder(my_folder_path)
