"""
JPYC決済サービス

ガスレス決済（EIP-3009 transferWithAuthorization）を実装
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any
import uuid
import logging
try:
    from eth_account.messages import encode_structured_data
except ImportError:
    # eth-account v0.9.0+ uses different import
    from eth_account.messages import encode_typed_data as encode_structured_data
from eth_account import Account
from web3 import Web3

logger = logging.getLogger(__name__)


class JPYCService:
    """JPYC決済サービス"""
    
    # JPYCコントラクトアドレス（チェーンごと）
    JPYC_CONTRACTS = {
        1: "0x...",  # Ethereum Mainnet（TODO: 実際のアドレスに置き換え）
        137: "0x...",  # Polygon（TODO: 実際のアドレスに置き換え）
        43114: "0x...",  # Avalanche（TODO: 実際のアドレスに置き換え）
    }
    
    # RPC URLs
    RPC_URLS = {
        1: "https://eth-mainnet.g.alchemy.com/v2/YOUR-API-KEY",  # TODO: 設定
        137: "https://polygon-mainnet.g.alchemy.com/v2/YOUR-API-KEY",  # TODO: 設定
        43114: "https://api.avax.network/ext/bc/C/rpc",
    }
    
    # プラットフォームのウォレットアドレス（TODO: 環境変数から取得）
    PLATFORM_ADDRESS = "0x0000000000000000000000000000000000000000"  # TODO: 設定
    
    # リレイヤーの秘密鍵（TODO: 環境変数から取得）
    RELAYER_PRIVATE_KEY = None  # TODO: 設定
    
    def __init__(self, chain_id: int):
        """
        初期化
        
        Args:
            chain_id: ブロックチェーンID
        """
        self.chain_id = chain_id
        self.jpyc_contract_address = self.JPYC_CONTRACTS.get(chain_id)
        
        if not self.jpyc_contract_address:
            raise ValueError(f"Unsupported chain_id: {chain_id}")
        
        # Web3インスタンス作成
        rpc_url = self.RPC_URLS.get(chain_id)
        if rpc_url:
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        else:
            self.w3 = None
    
    def verify_signature(
        self,
        from_address: str,
        to_address: str,
        value: int,
        valid_after: int,
        valid_before: int,
        nonce: str,
        signature_v: int,
        signature_r: str,
        signature_s: str,
    ) -> bool:
        """
        EIP-3009署名を検証
        
        Args:
            from_address: 送信元アドレス
            to_address: 送信先アドレス
            value: 金額（wei単位）
            valid_after: 有効開始時刻
            valid_before: 有効終了時刻
            nonce: nonce
            signature_v: 署名v
            signature_r: 署名r
            signature_s: 署名s
            
        Returns:
            bool: 署名が有効な場合True
        """
        try:
            # EIP-712構造化データ作成
            structured_data = {
                "types": {
                    "EIP712Domain": [
                        {"name": "name", "type": "string"},
                        {"name": "version", "type": "string"},
                        {"name": "chainId", "type": "uint256"},
                        {"name": "verifyingContract", "type": "address"},
                    ],
                    "TransferWithAuthorization": [
                        {"name": "from", "type": "address"},
                        {"name": "to", "type": "address"},
                        {"name": "value", "type": "uint256"},
                        {"name": "validAfter", "type": "uint256"},
                        {"name": "validBefore", "type": "uint256"},
                        {"name": "nonce", "type": "bytes32"},
                    ],
                },
                "primaryType": "TransferWithAuthorization",
                "domain": {
                    "name": "JPYCv2",
                    "version": "1",
                    "chainId": self.chain_id,
                    "verifyingContract": self.jpyc_contract_address,
                },
                "message": {
                    "from": from_address,
                    "to": to_address,
                    "value": value,
                    "validAfter": valid_after,
                    "validBefore": valid_before,
                    "nonce": nonce,
                },
            }
            
            # メッセージハッシュ作成
            encoded_data = encode_structured_data(structured_data)
            
            # 署名から署名者を復元
            signature = signature_r + signature_s[2:] + hex(signature_v)[2:]
            recovered_address = Account.recover_message(
                encoded_data,
                signature=signature
            )
            
            # 署名者が送信元アドレスと一致するか確認
            is_valid = recovered_address.lower() == from_address.lower()
            
            if is_valid:
                logger.info(f"✅ Signature verified for {from_address}")
            else:
                logger.warning(f"❌ Invalid signature for {from_address}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"❌ Signature verification failed: {str(e)}")
            return False
    
    def execute_transfer_with_authorization(
        self,
        from_address: str,
        to_address: str,
        value: int,
        valid_after: int,
        valid_before: int,
        nonce: str,
        signature_v: int,
        signature_r: str,
        signature_s: str,
    ) -> Optional[str]:
        """
        transferWithAuthorizationを実行
        
        TODO: リレイヤーの秘密鍵が設定されたら実装
        
        Args:
            from_address: 送信元アドレス
            to_address: 送信先アドレス
            value: 金額（wei単位）
            valid_after: 有効開始時刻
            valid_before: 有効終了時刻
            nonce: nonce
            signature_v: 署名v
            signature_r: 署名r
            signature_s: 署名s
            
        Returns:
            Optional[str]: トランザクションハッシュ、失敗時はNone
        """
        # TODO: ウォレット情報が揃ったら実装
        logger.warning("⚠️ execute_transfer_with_authorization is not implemented yet")
        logger.warning("⚠️ Waiting for relayer private key configuration")
        
        return None
    
    def get_transaction_status(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """
        トランザクションステータスを取得
        
        Args:
            tx_hash: トランザクションハッシュ
            
        Returns:
            Optional[Dict]: トランザクション情報、失敗時はNone
        """
        if not self.w3:
            logger.error("❌ Web3 not initialized")
            return None
        
        try:
            tx = self.w3.eth.get_transaction(tx_hash)
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
            
            return {
                "tx_hash": tx_hash,
                "block_number": receipt.get("blockNumber"),
                "status": "success" if receipt.get("status") == 1 else "failed",
                "gas_used": receipt.get("gasUsed"),
            }
        except Exception as e:
            logger.error(f"❌ Failed to get transaction status: {str(e)}")
            return None


# 便利関数
def jpyc_to_wei(jpyc_amount: int) -> int:
    """
    JPYC金額をwei単位に変換
    
    1 JPYC = 10^18 wei
    
    Args:
        jpyc_amount: JPYC金額
        
    Returns:
        int: wei単位の金額
    """
    return jpyc_amount * (10 ** 18)


def wei_to_jpyc(wei_amount: int) -> int:
    """
    wei単位の金額をJPYC金額に変換
    
    Args:
        wei_amount: wei単位の金額
        
    Returns:
        int: JPYC金額
    """
    return wei_amount // (10 ** 18)
